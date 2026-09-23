#include "nier/uinput_device.h"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <linux/input-event-codes.h>
#include <linux/uinput.h>
#include <stdexcept>
#include <sys/ioctl.h>
#include <sys/time.h>
#include <system_error>
#include <thread>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

namespace nier::uinput {
namespace {

[[noreturn]] void throw_errno(const char* operation) {
    throw std::system_error(errno, std::generic_category(), operation);
}

void require_ioctl(int fd, unsigned long request, unsigned long value, const char* operation) {
    if (ioctl(fd, request, value) < 0) {
        throw_errno(operation);
    }
}

void setup_axis(int fd, std::uint16_t code, std::int32_t minimum, std::int32_t maximum) {
    uinput_abs_setup axis{};
    axis.code = code;
    axis.absinfo.minimum = minimum;
    axis.absinfo.maximum = maximum;
    axis.absinfo.fuzz = 0;
    axis.absinfo.flat = 0;
    axis.absinfo.resolution = 0;
    if (ioctl(fd, UI_ABS_SETUP, &axis) < 0) {
        throw_errno("UI_ABS_SETUP");
    }
}

constexpr std::int64_t kInterpolationStepPixels = 16;

std::vector<Point> interpolate_points(const std::vector<Point>& points) {
    std::vector<Point> result;
    result.reserve(points.size());
    result.push_back(points.front());

    for (std::size_t index = 1; index < points.size(); ++index) {
        const auto& start = points[index - 1];
        const auto& end = points[index];
        const auto delta_x = static_cast<std::int64_t>(end.x) - start.x;
        const auto delta_y = static_cast<std::int64_t>(end.y) - start.y;
        const auto distance = std::max(
            delta_x >= 0 ? delta_x : -delta_x,
            delta_y >= 0 ? delta_y : -delta_y);
        const auto steps = std::max<std::int64_t>(
            1,
            (distance + kInterpolationStepPixels - 1) / kInterpolationStepPixels);

        for (std::int64_t step = 1; step <= steps; ++step) {
            const Point sample{
                static_cast<std::int32_t>(start.x + delta_x * step / steps),
                static_cast<std::int32_t>(start.y + delta_y * step / steps),
            };
            if (sample.x != result.back().x || sample.y != result.back().y) {
                result.push_back(sample);
            }
        }
    }
    return result;
}

void configure_device(int fd, const VirtualTouchDevice::Options& options) {
    require_ioctl(fd, UI_SET_EVBIT, EV_KEY, "UI_SET_EVBIT(EV_KEY)");
    require_ioctl(fd, UI_SET_EVBIT, EV_ABS, "UI_SET_EVBIT(EV_ABS)");
    require_ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH, "UI_SET_KEYBIT(BTN_TOUCH)");
    require_ioctl(fd, UI_SET_KEYBIT, BTN_TOOL_FINGER, "UI_SET_KEYBIT(BTN_TOOL_FINGER)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_SLOT, "UI_SET_ABSBIT(ABS_MT_SLOT)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_TRACKING_ID, "UI_SET_ABSBIT(ABS_MT_TRACKING_ID)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_POSITION_X, "UI_SET_ABSBIT(ABS_MT_POSITION_X)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_POSITION_Y, "UI_SET_ABSBIT(ABS_MT_POSITION_Y)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_TOUCH_MAJOR, "UI_SET_ABSBIT(ABS_MT_TOUCH_MAJOR)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_PRESSURE, "UI_SET_ABSBIT(ABS_MT_PRESSURE)");
    require_ioctl(fd, UI_SET_ABSBIT, ABS_MT_TOOL_TYPE, "UI_SET_ABSBIT(ABS_MT_TOOL_TYPE)");
    require_ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT, "UI_SET_PROPBIT(INPUT_PROP_DIRECT)");

    uinput_setup setup{};
    std::strncpy(setup.name, options.name.c_str(), UINPUT_MAX_NAME_SIZE - 1);
    setup.id.bustype = BUS_USB;
    setup.id.vendor = 0x1;
    setup.id.product = 0x1;
    setup.id.version = 1;
    if (ioctl(fd, UI_DEV_SETUP, &setup) < 0) {
        throw_errno("UI_DEV_SETUP");
    }

    const auto max_x = options.width - 1;
    const auto max_y = options.height - 1;
    setup_axis(fd, ABS_MT_SLOT, 0, 1);
    setup_axis(fd, ABS_MT_TRACKING_ID, 0, 1);
    setup_axis(fd, ABS_MT_POSITION_X, 0, max_x);
    setup_axis(fd, ABS_MT_POSITION_Y, 0, max_y);
    setup_axis(fd, ABS_MT_TOUCH_MAJOR, 0, 255);
    setup_axis(fd, ABS_MT_PRESSURE, 0, 255);
    setup_axis(fd, ABS_MT_TOOL_TYPE, 0, MT_TOOL_FINGER);

    if (ioctl(fd, UI_DEV_CREATE) < 0) {
        throw_errno("UI_DEV_CREATE");
    }
    // Android discovers the hot-plugged input node asynchronously. Without
    // this delay, the first command in a persistent or one-shot ADB session
    // can emit BTN_TOUCH before InputReader has registered the device,
    // dropping the initial position and turning the remaining events into an
    // unrelated edge gesture.
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
}

}  // namespace

VirtualTouchDevice VirtualTouchDevice::create(Options options) {
    validate_options(options);
    if (!is_root()) {
        throw std::system_error(EPERM, std::generic_category(), "uinput requires root");
    }

    const int fd = open(options.path.c_str(), O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        throw_errno(options.path.c_str());
    }

    try {
        configure_device(fd, options);
    } catch (...) {
        ::close(fd);
        throw;
    }
    return VirtualTouchDevice(fd, std::move(options));
}

bool VirtualTouchDevice::is_root() noexcept {
    return geteuid() == 0;
}

bool VirtualTouchDevice::path_available(const std::string& path) noexcept {
    return access(path.c_str(), W_OK) == 0;
}

bool VirtualTouchDevice::point_in_bounds(const Options& options, Point point) noexcept {
    return options.width > 0 && options.height > 0 && point.x >= 0 && point.y >= 0 &&
           point.x < options.width && point.y < options.height;
}

void VirtualTouchDevice::validate_options(const Options& options) {
    if (options.width <= 0 || options.height <= 0) {
        throw std::invalid_argument("uinput screen width and height must be positive");
    }
    if (options.path.empty()) {
        throw std::invalid_argument("uinput device path must not be empty");
    }
    if (options.name.empty() || options.name.size() >= UINPUT_MAX_NAME_SIZE) {
        throw std::invalid_argument("uinput device name must contain 1-79 bytes");
    }
}

VirtualTouchDevice::VirtualTouchDevice(int fd, Options options) noexcept
    : fd_(fd), options_(std::move(options)) {}

VirtualTouchDevice::VirtualTouchDevice(VirtualTouchDevice&& other) noexcept
    : fd_(other.fd_), options_(std::move(other.options_)), touching_(other.touching_), tracking_id_(other.tracking_id_) {
    other.fd_ = -1;
    other.touching_ = false;
}

VirtualTouchDevice& VirtualTouchDevice::operator=(VirtualTouchDevice&& other) noexcept {
    if (this == &other) return *this;
    close();
    fd_ = other.fd_;
    options_ = std::move(other.options_);
    touching_ = other.touching_;
    tracking_id_ = other.tracking_id_;
    other.fd_ = -1;
    other.touching_ = false;
    return *this;
}

VirtualTouchDevice::~VirtualTouchDevice() noexcept {
    close();
}

void VirtualTouchDevice::validate_point(Point point) const {
    if (!point_in_bounds(options_, point)) {
        throw std::out_of_range("touch point is outside the configured screen bounds");
    }
}

void VirtualTouchDevice::emit(std::uint16_t type, std::uint16_t code, std::int32_t value) {
    input_event event{};
    event.type = type;
    event.code = code;
    event.value = value;
    if (gettimeofday(&event.time, nullptr) < 0) {
        throw_errno("gettimeofday");
    }

    const auto* bytes = reinterpret_cast<const std::uint8_t*>(&event);
    std::size_t written = 0;
    while (written < sizeof(event)) {
        const auto result = write(fd_, bytes + written, sizeof(event) - written);
        if (result < 0) {
            if (errno == EINTR) continue;
            throw_errno("write(uinput event)");
        }
        if (result == 0) {
            throw std::system_error(EIO, std::generic_category(), "write(uinput event)");
        }
        written += static_cast<std::size_t>(result);
    }
}

void VirtualTouchDevice::sync() {
    emit(EV_SYN, SYN_REPORT, 0);
}

void VirtualTouchDevice::set_position(Point point) {
    emit(EV_ABS, ABS_MT_SLOT, 0);
    emit(EV_ABS, ABS_MT_POSITION_X, point.x);
    emit(EV_ABS, ABS_MT_POSITION_Y, point.y);
    emit(EV_ABS, ABS_MT_TOUCH_MAJOR, 1);
    emit(EV_ABS, ABS_MT_PRESSURE, 1);
    emit(EV_ABS, ABS_MT_TOOL_TYPE, MT_TOOL_FINGER);
}

void VirtualTouchDevice::touch_down(Point point) {
    validate_point(point);
    if (touching_) {
        throw std::logic_error("touch is already active");
    }
    emit(EV_ABS, ABS_MT_SLOT, 0);
    emit(EV_ABS, ABS_MT_TRACKING_ID, tracking_id_++);
    set_position(point);
    emit(EV_KEY, BTN_TOUCH, 1);
    emit(EV_KEY, BTN_TOOL_FINGER, 1);
    sync();
    touching_ = true;
}

void VirtualTouchDevice::touch_move(Point point) {
    validate_point(point);
    if (!touching_) {
        throw std::logic_error("touch is not active");
    }
    set_position(point);
    sync();
}

void VirtualTouchDevice::touch_up() {
    if (!touching_) return;
    emit(EV_ABS, ABS_MT_SLOT, 0);
    emit(EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit(EV_ABS, ABS_MT_TOUCH_MAJOR, 0);
    emit(EV_ABS, ABS_MT_PRESSURE, 0);
    emit(EV_KEY, BTN_TOUCH, 0);
    emit(EV_KEY, BTN_TOOL_FINGER, 0);
    sync();
    touching_ = false;
}

void VirtualTouchDevice::click(Point point, std::chrono::milliseconds duration) {
    if (duration.count() < 0) {
        throw std::invalid_argument("click duration must not be negative");
    }
    touch_down(point);
    try {
        std::this_thread::sleep_for(duration);
        touch_up();
    } catch (...) {
        try {
            touch_up();
        } catch (...) {
            close();
        }
        throw;
    }
}

void VirtualTouchDevice::swipe(const std::vector<Point>& points, std::chrono::milliseconds duration) {
    if (points.size() < 2) {
        throw std::invalid_argument("swipe requires at least two points");
    }
    if (duration.count() <= 0) {
        throw std::invalid_argument("swipe duration must be positive");
    }
    for (const auto point : points) validate_point(point);

    const auto samples = interpolate_points(points);
    touch_down(samples.front());
    try {
        const auto start = std::chrono::steady_clock::now();
        const auto segments = samples.size() - 1;
        for (std::size_t index = 1; index < samples.size(); ++index) {
            const auto elapsed = duration * static_cast<std::int64_t>(index) /
                                 static_cast<std::int64_t>(segments);
            std::this_thread::sleep_until(start + elapsed);
            touch_move(samples[index]);
        }
        touch_up();
    } catch (...) {
        try {
            touch_up();
        } catch (...) {
            close();
        }
        throw;
    }
}

void VirtualTouchDevice::close() noexcept {
    if (fd_ < 0) return;
    try {
        if (touching_) touch_up();
    } catch (...) {
        // Device destruction must continue even if the release event fails.
    }
    ioctl(fd_, UI_DEV_DESTROY);
    ::close(fd_);
    fd_ = -1;
    touching_ = false;
}

}  // namespace nier::uinput
