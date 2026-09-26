package icu.rina.nier.backend

import android.util.Log

/** Optional, machine-local integration for non-standard WebView providers. */
interface WebViewDebugAdapter {
    fun install(context: WebViewDebugAdapterContext)
}

/** Runtime details exposed to an optional adapter inside the target app process. */
data class WebViewDebugAdapterContext(
    val packageName: String,
    val processName: String,
    val appClassLoader: ClassLoader,
    val reporter: WebViewDebugAdapterReporter,
)

/** Reports adapter endpoints through a stable, vendor-neutral log protocol. */
class WebViewDebugAdapterReporter internal constructor(
    private val packageName: String,
) {
    fun reportLoopbackTcpPort(port: Int) {
        require(port in 1..65535) { "port must be between 1 and 65535" }
        Log.i(
            TAG,
            "NIER_WEBVIEW_ADAPTER_V1|READY|$packageName|${android.os.Process.myPid()}|tcp|$port",
        )
    }

    fun reportError(message: String) {
        val safeMessage = "[$packageName] " +
            message.replace('|', '/').replace('\n', ' ').take(MAX_MESSAGE_LENGTH)
        Log.e(
            TAG,
            "NIER_WEBVIEW_ADAPTER_V1|ERROR|$packageName|${android.os.Process.myPid()}|$safeMessage",
        )
    }

    private companion object {
        const val TAG = "NierWebViewHook"
        const val MAX_MESSAGE_LENGTH = 240
    }
}
