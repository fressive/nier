package icu.rina.nier.backend

import android.webkit.WebView

/**
 * Cooperative, non-root WebView integration for an application that owns the
 * WebView. It must be called before the first WebView is created.
 */
object WebViewDebugController {
    @JvmStatic
    fun enable() {
        WebView.setWebContentsDebuggingEnabled(true)
    }
}
