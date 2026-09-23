package icu.rina.nier.backend

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Bundle
import android.os.Process
import android.util.Base64

/**
 * Narrow ADB command bridge for the optional Nier IME.
 *
 * The provider is exported because `adb shell content call` needs to reach it.
 * It accepts calls only from the shell/root UID or from this application's own
 * UID; ordinary third-party applications cannot submit text through it.
 */
class NierInputCommandProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle? {
        enforceCaller()
        if (method != METHOD_COMMIT_TEXT) {
            return failure("unsupported method: $method")
        }

        val encoded = extras?.getString(EXTRA_TEXT_B64)
            ?: return failure("missing text_b64 extra")
        val text = try {
            val bytes = Base64.decode(encoded, Base64.URL_SAFE or Base64.NO_WRAP)
            bytes.toString(Charsets.UTF_8)
        } catch (_: IllegalArgumentException) {
            return failure("text_b64 is not valid URL-safe Base64")
        }

        return if (NierInputMethodService.commitFromHost(text)) {
            Bundle().apply { putBoolean(KEY_OK, true) }
        } else {
            failure("no active InputConnection")
        }
    }

    private fun enforceCaller() {
        val uid = Binder.getCallingUid()
        if (uid != Process.SHELL_UID && uid != ROOT_UID && uid != Process.myUid()) {
            throw SecurityException("only adb shell/root may call the Nier input provider")
        }
    }

    private fun failure(message: String): Bundle = Bundle().apply {
        putBoolean(KEY_OK, false)
        putString(KEY_ERROR, message)
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0

    companion object {
        private const val METHOD_COMMIT_TEXT = "commit_text"
        private const val EXTRA_TEXT_B64 = "text_b64"
        private const val KEY_OK = "ok"
        private const val KEY_ERROR = "error"
        private const val ROOT_UID = 0
    }
}
