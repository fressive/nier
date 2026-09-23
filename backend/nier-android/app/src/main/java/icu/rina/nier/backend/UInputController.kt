package icu.rina.nier.backend

/** Root-only virtual touch device bridge. */
class UInputController private constructor(
    private val handle: Long,
) {
    fun click(x: Int, y: Int, durationMs: Long) {
        nativeClick(handle, x, y, durationMs)
    }

    fun swipe(points: List<Pair<Int, Int>>, durationMs: Long) {
        require(points.size >= 2)
        nativeSwipe(handle, points.map { it.first }.toIntArray(), points.map { it.second }.toIntArray(), durationMs)
    }

    fun close() {
        nativeClose(handle)
    }

    companion object {
        init {
            try {
                System.loadLibrary("nier_uinput")
            } catch (_: UnsatisfiedLinkError) {
                // The shell implementation remains available on non-root or
                // APK-only builds that do not package the native library.
            }
        }

        fun tryCreate(width: Int, height: Int): UInputController? = try {
            val handle = nativeInit(width, height)
            if (handle == 0L) null else UInputController(handle)
        } catch (_: UnsatisfiedLinkError) {
            null
        } catch (_: RuntimeException) {
            null
        }

        @JvmStatic private external fun nativeInit(width: Int, height: Int): Long
        @JvmStatic private external fun nativeClick(handle: Long, x: Int, y: Int, durationMs: Long)
        @JvmStatic private external fun nativeSwipe(handle: Long, xs: IntArray, ys: IntArray, durationMs: Long)
        @JvmStatic private external fun nativeClose(handle: Long)
    }
}
