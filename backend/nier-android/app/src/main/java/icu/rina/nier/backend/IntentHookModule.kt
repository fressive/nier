package icu.rina.nier.backend

import android.app.Instrumentation
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.util.Log
import de.robv.android.xposed.IXposedHookLoadPackage
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedBridge
import de.robv.android.xposed.XposedHelpers
import de.robv.android.xposed.callbacks.XC_LoadPackage
import org.json.JSONArray
import org.json.JSONObject
import java.lang.reflect.Array as ReflectArray
import java.lang.reflect.Field
import java.util.Collections
import java.util.IdentityHashMap
import java.util.concurrent.atomic.AtomicLong

class IntentHookModule : IXposedHookLoadPackage {
    override fun handleLoadPackage(loadPackageParam: XC_LoadPackage.LoadPackageParam) {
        val loadedPackageName = loadPackageParam.packageName ?: return
        val processName = loadPackageParam.processName ?: loadedPackageName
        val processPackageName = processName.substringBefore(':')
        val packageName = if (processPackageName.contains('.')) {
            processPackageName
        } else {
            loadedPackageName
        }
        if (loadedPackageName == MODULE_PACKAGE || packageName == MODULE_PACKAGE) return

        val captureHook = object : XC_MethodHook() {
            override fun beforeHookedMethod(param: MethodHookParam) {
                IntentEventLogger.beginLaunchCall()
            }

            override fun afterHookedMethod(param: MethodHookParam) {
                try {
                    if (param.throwable != null) return
                    param.args.forEach { argument ->
                        when (argument) {
                            is Intent -> IntentEventLogger.capture(
                                packageName = packageName,
                                processName = processName,
                                intent = argument,
                                source = param.method.name,
                            )
                            is Array<*> -> argument.filterIsInstance<Intent>().forEach { intent ->
                                IntentEventLogger.capture(
                                    packageName = packageName,
                                    processName = processName,
                                    intent = intent,
                                    source = param.method.name,
                                )
                            }
                        }
                    }
                } finally {
                    IntentEventLogger.endLaunchCall()
                }
            }
        }

        var installed = 0
        val hookSources = JSONObject()
        val instrumentationHooks = hookMethods(
            Instrumentation::class.java,
            setOf("execStartActivity", "execStartActivities"),
            captureHook,
        )
        installed += instrumentationHooks
        hookSources.put("Instrumentation", instrumentationHooks)

        var contextImplHooks = 0
        try {
            val contextImpl = XposedHelpers.findClass("android.app.ContextImpl", null)
            contextImplHooks = hookMethods(
                contextImpl,
                setOf("startActivity", "startActivities"),
                captureHook,
            )
            installed += contextImplHooks
        } catch (error: Throwable) {
            XposedBridge.log("Nier Intent hook: ContextImpl hook failed: " + error)
        }
        hookSources.put("ContextImpl", contextImplHooks)

        val activityManagerProxyClasses = listOf(
            "android.app.IActivityTaskManager\$Stub\$Proxy",
            "android.app.IActivityManager\$Stub\$Proxy",
        )
        val activityManagerLaunchMethods = setOf(
            "startActivity",
            "startActivityAsUser",
            "startActivityWithFeature",
            "startActivityAsUserWithFeature",
            "startActivities",
            "startActivitiesAsUser",
        )
        activityManagerProxyClasses.forEach { className ->
            val proxyClass = XposedHelpers.findClassIfExists(className, null) ?: return@forEach
            val proxyHooks = hookMethods(proxyClass, activityManagerLaunchMethods, captureHook)
            installed += proxyHooks
            hookSources.put(className, proxyHooks)
        }

        var activityThreadHooks = 0
        if (installed == 0) {
            try {
                val activityThread = XposedHelpers.findClass("android.app.ActivityThread", null)
                val activityDeliveryHook = object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        if (IntentEventLogger.consumeInitialActivityLaunch()) return
                        IntentEventLogger.beginLaunchCall()
                        try {
                            val intent = param.args.firstOrNull { it is Intent } as? Intent
                                ?: param.args.asSequence()
                                    .filterNotNull()
                                    .mapNotNull { record ->
                                        try {
                                            XposedHelpers.getObjectField(record, "intent") as? Intent
                                        } catch (_: Throwable) {
                                            null
                                        }
                                    }
                                    .firstOrNull()
                                ?: return
                            IntentEventLogger.capture(
                                packageName = packageName,
                                processName = processName,
                                intent = intent,
                                source = param.method.name,
                                activityDelivery = true,
                            )
                        } finally {
                            IntentEventLogger.endLaunchCall()
                        }
                    }
                }
                activityThreadHooks = hookMethods(
                    activityThread,
                    setOf("performLaunchActivity"),
                    activityDeliveryHook,
                )
                installed += activityThreadHooks
            } catch (error: Throwable) {
                XposedBridge.log("Nier Intent hook: ActivityThread hook failed: " + error)
            }
        }
        hookSources.put("ActivityThread", activityThreadHooks)

        if (installed > 0) {
            IntentEventLogger.moduleReady(
                packageName,
                processName,
                installed,
                hookSources,
            )
        } else {
            IntentEventLogger.moduleError(
                packageName,
                processName,
                "no Activity launch methods were available to hook",
            )
        }
    }

    private companion object {
        const val MODULE_PACKAGE = "icu.rina.nier.backend"

        fun hookMethods(
            targetClass: Class<*>,
            methodNames: Set<String>,
            callback: XC_MethodHook,
        ): Int {
            var installed = 0
            methodNames.forEach { methodName ->
                try {
                    installed += XposedBridge.hookAllMethods(
                        targetClass,
                        methodName,
                        callback,
                    ).size
                } catch (error: Throwable) {
                    XposedBridge.log(
                        "Nier Intent hook: ${targetClass.name}#$methodName hook failed: $error",
                    )
                }
            }
            return installed
        }
    }
}

private object IntentEventLogger {
    private const val TAG = "NierIntentHook"
    private const val MAX_LOG_MESSAGE = 2400
    private const val MAX_EVENT_BYTES = 512 * 1024
    private val nextEventId = AtomicLong()
    private val initialActivityLaunch = java.util.concurrent.atomic.AtomicBoolean(true)
    private val launchDepth = ThreadLocal<Int>()
    private val capturedInCall = ThreadLocal<MutableSet<Intent>>()
    private val recentLaunchLock = Any()
    private val recentLaunches = mutableListOf<RecentLaunch>()

    private data class RecentLaunch(val intent: Intent, val elapsedRealtime: Long)

    fun moduleReady(
        packageName: String,
        processName: String,
        hookCount: Int,
        hookSources: JSONObject,
    ) {
        emit(
            JSONObject()
                .put("event", "module_ready")
                .put("package", packageName)
                .put("process", processName)
                .put("pid", android.os.Process.myPid())
                .put("hooks", hookCount)
                .put("hook_sources", hookSources),
        )
    }

    fun consumeInitialActivityLaunch(): Boolean = initialActivityLaunch.getAndSet(false)

    fun moduleError(packageName: String, processName: String, message: String) {
        emit(
            JSONObject()
                .put("event", "module_error")
                .put("package", packageName)
                .put("process", processName)
                .put("pid", android.os.Process.myPid())
                .put("error", message),
        )
    }

    fun capture(
        packageName: String,
        processName: String,
        intent: Intent,
        source: String,
        activityDelivery: Boolean = false,
    ) {
        if (!currentCaptureSet().add(intent)) return
        if (activityDelivery && consumeRecentLaunch(intent)) return

        try {
            val payload = JSONObject()
                .put("event", "intent")
                .put("package", packageName)
                .put("process", processName)
                .put("pid", android.os.Process.myPid())
                .put("source", source)
                .put("intent", intentToJson(intent))
            emit(payload)
            if (!activityDelivery) rememberLaunch(intent)
        } catch (error: Throwable) {
            emit(
                JSONObject()
                    .put("event", "capture_error")
                    .put("package", packageName)
                    .put("process", processName)
                    .put("pid", android.os.Process.myPid())
                    .put("error", error.javaClass.name),
            )
        }
    }

    fun beginLaunchCall() {
        val depth = launchDepth.get() ?: 0
        if (depth == 0) currentCaptureSet().clear()
        launchDepth.set(depth + 1)
    }

    fun endLaunchCall() {
        val depth = (launchDepth.get() ?: 0) - 1
        if (depth <= 0) {
            capturedInCall.get()?.clear()
            launchDepth.remove()
            capturedInCall.remove()
        } else {
            launchDepth.set(depth)
        }
    }

    private fun currentCaptureSet(): MutableSet<Intent> {
        val current = capturedInCall.get()
        if (current != null) return current
        val created = Collections.newSetFromMap(IdentityHashMap<Intent, Boolean>())
        capturedInCall.set(created)
        return created
    }

    private fun rememberLaunch(intent: Intent) {
        val now = android.os.SystemClock.elapsedRealtime()
        synchronized(recentLaunchLock) {
            recentLaunches.removeAll { now - it.elapsedRealtime > RECENT_LAUNCH_WINDOW_MS }
            recentLaunches.add(RecentLaunch(Intent(intent), now))
        }
    }

    private fun consumeRecentLaunch(intent: Intent): Boolean {
        val now = android.os.SystemClock.elapsedRealtime()
        synchronized(recentLaunchLock) {
            recentLaunches.removeAll { now - it.elapsedRealtime > RECENT_LAUNCH_WINDOW_MS }
            val index = recentLaunches.indexOfFirst { it.intent.filterEquals(intent) }
            if (index < 0) return false
            recentLaunches.removeAt(index)
            return true
        }
    }

    private fun intentToJson(intent: Intent): JSONObject {
        val component = intent.component
        val action = clipped(intent.action)
        val data = clipped(intent.dataString)
        val mimeType = clipped(intent.type)
        val packageValue = clipped(intent.getPackage())
        val categories = JSONArray()
        var categoriesTruncated = false
        val categoryIterator = intent.categories?.iterator()
        if (categoryIterator != null) {
            var count = 0
            while (categoryIterator.hasNext()) {
                val category = categoryIterator.next()
                if (count >= MAX_EXTRA_COUNT) {
                    categoriesTruncated = true
                    break
                }
                val clippedCategory = clipped(category)
                categories.put(clippedCategory.first)
                categoriesTruncated = categoriesTruncated || clippedCategory.second
                count += 1
            }
        }

        val flags = intent.flags
        val flagNames = JSONArray()
        KNOWN_FLAGS.forEach { (bit, name) ->
            if (flags and bit != 0) flagNames.put(name)
        }

        val extras = readExtras(intent.extras)
        return JSONObject()
            .put("component", component?.let { componentToJson(it) } ?: JSONObject.NULL)
            .put("action", action.first ?: JSONObject.NULL)
            .put("action_truncated", action.second)
            .put("data", data.first ?: JSONObject.NULL)
            .put("data_truncated", data.second)
            .put("type", mimeType.first ?: JSONObject.NULL)
            .put("type_truncated", mimeType.second)
            .put("package", packageValue.first ?: JSONObject.NULL)
            .put("package_truncated", packageValue.second)
            .put("flags", flags)
            .put("flags_hex", "0x" + (flags.toLong() and 0xffffffffL).toString(16).padStart(8, '0'))
            .put("flag_names", flagNames)
            .put("categories", categories)
            .put("categories_truncated", categoriesTruncated)
            .put("extras", extras.values)
            .put("extras_truncated", extras.truncated)
            .put("extras_unavailable", extras.unavailable)
    }

    private data class ExtrasResult(
        val values: JSONObject,
        val truncated: Boolean,
        val unavailable: Boolean,
    )

    private fun readExtras(bundle: Bundle?): ExtrasResult {
        val values = JSONObject()
        if (bundle == null) return ExtrasResult(values, truncated = false, unavailable = false)

        val backingMap = try {
            findField(bundle.javaClass, "mMap")?.get(bundle)
        } catch (_: Throwable) {
            null
        }
        if (backingMap !is Map<*, *>) {
            return ExtrasResult(values, truncated = false, unavailable = true)
        }

        var truncated = false
        var count = 0
        for ((key, value) in backingMap) {
            if (count >= MAX_EXTRA_COUNT) {
                truncated = true
                break
            }
            if (key is String) {
                values.put(key, extraToJson(value))
                count += 1
            }
        }
        return ExtrasResult(values, truncated, unavailable = false)
    }

    private fun extraToJson(value: Any?): JSONObject {
        if (value == null) return tagged("null", JSONObject.NULL)
        return when (value) {
            is String -> {
                val text = clipped(value)
                tagged("string", text.first, text.second)
            }
            is Boolean -> tagged("boolean", value)
            is Byte -> tagged("byte", value.toInt())
            is Short -> tagged("short", value.toInt())
            is Int -> tagged("int", value)
            is Long -> tagged("long", value.toString())
            is Float -> if (value.isFinite()) tagged("float", value.toDouble()) else unsupported(value)
            is Double -> if (value.isFinite()) tagged("double", value) else unsupported(value)
            is Char -> tagged("char", value.toString())
            is Uri -> {
                val text = clipped(value.toString())
                tagged("uri", text.first, text.second)
            }
            is ComponentName -> tagged("component", componentToJson(value))
            else -> if (value.javaClass.isArray) arrayToJson(value) else unsupported(value)
        }
    }

    private fun arrayToJson(value: Any): JSONObject {
        val componentType = value.javaClass.componentType ?: return unsupported(value)
        val kind = when (componentType) {
            java.lang.Boolean.TYPE -> "boolean"
            java.lang.Byte.TYPE -> "byte"
            java.lang.Short.TYPE -> "short"
            java.lang.Integer.TYPE -> "int"
            java.lang.Long.TYPE -> "long"
            java.lang.Float.TYPE -> "float"
            java.lang.Double.TYPE -> "double"
            java.lang.Character.TYPE -> "char"
            String::class.java -> "string"
            else -> return unsupported(value)
        }
        val length = ReflectArray.getLength(value)
        if (length == 0) return unsupported(value)
        val capturedLength = minOf(length, MAX_ARRAY_ITEMS)
        val values = JSONArray()
        var itemTruncated = false
        for (index in 0 until capturedLength) {
            val item = extraToJson(ReflectArray.get(value, index))
            if (item.optString("type") == "unsupported" || item.optString("type") == "null") {
                return unsupported(value)
            }
            itemTruncated = itemTruncated || item.optBoolean("truncated")
            values.put(item.opt("value"))
        }
        return tagged(kind + "_array", values, length > MAX_ARRAY_ITEMS || itemTruncated)
    }

    private fun componentToJson(component: ComponentName): JSONObject =
        JSONObject()
            .put("package", component.packageName)
            .put("class", component.className)

    private fun tagged(type: String, value: Any?, truncated: Boolean = false): JSONObject {
        val result = JSONObject().put("type", type).put("value", value ?: JSONObject.NULL)
        if (truncated) result.put("truncated", true)
        return result
    }

    private fun unsupported(value: Any): JSONObject =
        JSONObject()
            .put("type", "unsupported")
            .put("value", value.javaClass.name)

    private fun clipped(value: String?): Pair<String?, Boolean> {
        if (value == null) return null to false
        if (value.length <= MAX_TEXT_LENGTH) return value to false
        return value.substring(0, MAX_TEXT_LENGTH) + "…" to true
    }

    private fun findField(type: Class<*>, name: String): Field? {
        var current: Class<*>? = type
        while (current != null) {
            try {
                return current.getDeclaredField(name).apply { isAccessible = true }
            } catch (_: NoSuchFieldException) {
                current = current.superclass
            }
        }
        return null
    }

    private fun emit(event: JSONObject) {
        val json = boundEvent(event)
        val encoded = Base64.encodeToString(json.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
        val chunks = encoded.chunked(MAX_LOG_MESSAGE)
        val eventId = android.os.Process.myPid().toString() + "-" + nextEventId.incrementAndGet()
        chunks.forEachIndexed { index, chunk ->
            Log.i(
                TAG,
                "NIER_INTENT_V1|" + eventId + "|" + (index + 1) + "/" + chunks.size + "|" + chunk,
            )
        }
    }

    private fun boundEvent(event: JSONObject): String {
        var json = event.toString()
        val intent = event.optJSONObject("intent")
        val extras = intent?.optJSONObject("extras")
        if (intent != null && extras != null) {
            val names = mutableListOf<String>()
            val iterator = extras.keys()
            while (iterator.hasNext()) names.add(iterator.next())
            for (name in names.asReversed()) {
                if (json.toByteArray(Charsets.UTF_8).size <= MAX_EVENT_BYTES) break
                extras.remove(name)
                intent.put("extras_truncated", true)
                json = event.toString()
            }
            if (json.toByteArray(Charsets.UTF_8).size > MAX_EVENT_BYTES) {
                names.forEach { extras.remove(it) }
                intent.put("extras_truncated", true)
                json = event.toString()
            }
            val categories = intent.optJSONArray("categories")
            while (
                json.toByteArray(Charsets.UTF_8).size > MAX_EVENT_BYTES &&
                categories != null &&
                categories.length() > 0
            ) {
                categories.remove(categories.length() - 1)
                intent.put("categories_truncated", true)
                json = event.toString()
            }
        }
        return json
    }

    private const val MAX_EXTRA_COUNT = 100
    private const val MAX_ARRAY_ITEMS = 64
    private const val MAX_TEXT_LENGTH = 4096
    private const val RECENT_LAUNCH_WINDOW_MS = 10_000L
    private val KNOWN_FLAGS = listOf(
        0x10000000 to "FLAG_ACTIVITY_NEW_TASK",
        0x04000000 to "FLAG_ACTIVITY_CLEAR_TOP",
        0x20000000 to "FLAG_ACTIVITY_SINGLE_TOP",
        0x08000000 to "FLAG_ACTIVITY_MULTIPLE_TASK",
        0x40000000 to "FLAG_ACTIVITY_NO_HISTORY",
        0x02000000 to "FLAG_ACTIVITY_FORWARD_RESULT",
        0x01000000 to "FLAG_ACTIVITY_PREVIOUS_IS_TOP",
        0x00800000 to "FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS",
        0x00400000 to "FLAG_ACTIVITY_BROUGHT_TO_FRONT",
        0x00100000 to "FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY",
        0x00080000 to "FLAG_ACTIVITY_NEW_DOCUMENT",
        0x00040000 to "FLAG_ACTIVITY_NO_USER_ACTION",
        0x00020000 to "FLAG_ACTIVITY_REORDER_TO_FRONT",
        0x00010000 to "FLAG_ACTIVITY_NO_ANIMATION",
        0x00008000 to "FLAG_ACTIVITY_CLEAR_TASK",
        0x00004000 to "FLAG_ACTIVITY_TASK_ON_HOME",
    )
}
