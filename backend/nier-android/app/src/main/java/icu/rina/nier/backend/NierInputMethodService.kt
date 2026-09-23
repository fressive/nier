package icu.rina.nier.backend

import android.inputmethodservice.InputMethodService
import android.os.Handler
import android.os.Looper
import android.view.View
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Headless IME endpoint used by the optional host-side IME text backend.
 *
 * The service deliberately has no input UI. It commits a complete text value
 * through the focused editor's InputConnection when requested by the
 * same-package ContentProvider.
 */
class NierInputMethodService : InputMethodService() {
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onCreate() {
        super.onCreate()
        active = this
    }

    override fun onDestroy() {
        if (active === this) {
            active = null
        }
        super.onDestroy()
    }

    override fun onCreateInputView(): View? = null

    private fun commitOnMainThread(text: String, timeoutMs: Long): Boolean {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return commitNow(text)
        }

        val done = CountDownLatch(1)
        val accepted = AtomicBoolean(false)
        mainHandler.post {
            try {
                accepted.set(commitNow(text))
            } finally {
                done.countDown()
            }
        }
        return try {
            done.await(timeoutMs, TimeUnit.MILLISECONDS) && accepted.get()
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }
    }

    private fun commitNow(text: String): Boolean {
        val connection = currentInputConnection ?: return false
        return try {
            connection.commitText(text, 1)
        } catch (_: RuntimeException) {
            false
        }
    }

    companion object {
        private const val COMMIT_TIMEOUT_MS = 4_000L

        @Volatile
        private var active: NierInputMethodService? = null

        @JvmStatic
        fun commitFromHost(text: String): Boolean {
            return active?.commitOnMainThread(text, COMMIT_TIMEOUT_MS) == true
        }
    }
}
