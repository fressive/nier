#include <android/log.h>
#include <fcntl.h>
#include <jni.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <thread>

namespace {
constexpr char kTag[] = "NierUInput";

struct Device {
    int fd = -1;
    int width = 1;
    int height = 1;
};

void emit(int fd, uint16_t type, uint16_t code, int32_t value) {
    input_event event{};
    event.type = type;
    event.code = code;
    event.value = value;
    gettimeofday(&event.time, nullptr);
    if (write(fd, &event, sizeof(event)) != sizeof(event)) {
        __android_log_print(ANDROID_LOG_ERROR, kTag, "uinput write failed");
    }
}

void sync(int fd) { emit(fd, EV_SYN, SYN_REPORT, 0); }

void move(Device* device, int x, int y) {
    emit(device->fd, EV_ABS, ABS_X, std::clamp(x, 0, device->width - 1));
    emit(device->fd, EV_ABS, ABS_Y, std::clamp(y, 0, device->height - 1));
    sync(device->fd);
}

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_icu_rina_nier_backend_UInputController_nativeInit(JNIEnv*, jclass, jint width, jint height) {
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) return 0;

    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH);
    ioctl(fd, UI_SET_EVBIT, EV_ABS);
    ioctl(fd, UI_SET_ABSBIT, ABS_X);
    ioctl(fd, UI_SET_ABSBIT, ABS_Y);

    uinput_user_dev device{};
    std::strncpy(device.name, "Nier Virtual Touch", UINPUT_MAX_NAME_SIZE - 1);
    device.id.bustype = BUS_USB;
    device.id.vendor = 0x1;
    device.id.product = 0x1;
    device.id.version = 1;
    device.absmin[ABS_X] = 0;
    device.absmax[ABS_X] = std::max(1, static_cast<int>(width) - 1);
    device.absmin[ABS_Y] = 0;
    device.absmax[ABS_Y] = std::max(1, static_cast<int>(height) - 1);
    if (write(fd, &device, sizeof(device)) != sizeof(device) || ioctl(fd, UI_DEV_CREATE) < 0) {
        close(fd);
        return 0;
    }

    auto* handle = new Device{fd, std::max(1, static_cast<int>(width)), std::max(1, static_cast<int>(height))};
    return reinterpret_cast<jlong>(handle);
}

extern "C" JNIEXPORT void JNICALL
Java_icu_rina_nier_backend_UInputController_nativeClick(JNIEnv*, jclass, jlong raw, jint x, jint y, jlong duration_ms) {
    auto* device = reinterpret_cast<Device*>(raw);
    if (!device) return;
    move(device, x, y);
    emit(device->fd, EV_KEY, BTN_TOUCH, 1);
    sync(device->fd);
    std::this_thread::sleep_for(std::chrono::milliseconds(std::max<jlong>(0, duration_ms)));
    emit(device->fd, EV_KEY, BTN_TOUCH, 0);
    sync(device->fd);
}

extern "C" JNIEXPORT void JNICALL
Java_icu_rina_nier_backend_UInputController_nativeSwipe(JNIEnv* env, jclass, jlong raw, jintArray xs, jintArray ys, jlong duration_ms) {
    auto* device = reinterpret_cast<Device*>(raw);
    if (!device) return;
    const jsize size = env->GetArrayLength(xs);
    if (size < 2 || env->GetArrayLength(ys) != size) return;
    jboolean x_copy = JNI_FALSE;
    jboolean y_copy = JNI_FALSE;
    auto* x_values = env->GetIntArrayElements(xs, &x_copy);
    auto* y_values = env->GetIntArrayElements(ys, &y_copy);
    emit(device->fd, EV_KEY, BTN_TOUCH, 1);
    const auto step = std::max<jlong>(1, duration_ms / (size - 1));
    for (jsize i = 0; i < size; ++i) {
        move(device, x_values[i], y_values[i]);
        if (i + 1 < size) std::this_thread::sleep_for(std::chrono::milliseconds(step));
    }
    emit(device->fd, EV_KEY, BTN_TOUCH, 0);
    sync(device->fd);
    env->ReleaseIntArrayElements(xs, x_values, JNI_ABORT);
    env->ReleaseIntArrayElements(ys, y_values, JNI_ABORT);
}

extern "C" JNIEXPORT void JNICALL
Java_icu_rina_nier_backend_UInputController_nativeClose(JNIEnv*, jclass, jlong raw) {
    auto* device = reinterpret_cast<Device*>(raw);
    if (!device) return;
    ioctl(device->fd, UI_DEV_DESTROY);
    close(device->fd);
    delete device;
}
