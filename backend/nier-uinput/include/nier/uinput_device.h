#pragma once

#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

namespace nier::uinput {

struct Point {
    std::int32_t x = 0;
    std::int32_t y = 0;
};

class VirtualTouchDevice final {
public:
    struct Options {
        std::int32_t width = 0;
        std::int32_t height = 0;
        std::string path = "/dev/uinput";
        std::string name = "Nier Virtual Touch";
    };

    // Throws std::invalid_argument for bad dimensions/name and std::system_error
    // when root or the uinput device is unavailable.
    static VirtualTouchDevice create(Options options);

    static bool is_root() noexcept;
    static bool path_available(const std::string& path) noexcept;
    static bool point_in_bounds(const Options& options, Point point) noexcept;
    static void validate_options(const Options& options);

    VirtualTouchDevice(const VirtualTouchDevice&) = delete;
    VirtualTouchDevice& operator=(const VirtualTouchDevice&) = delete;
    VirtualTouchDevice(VirtualTouchDevice&& other) noexcept;
    VirtualTouchDevice& operator=(VirtualTouchDevice&& other) noexcept;
    ~VirtualTouchDevice() noexcept;

    void click(Point point, std::chrono::milliseconds duration = std::chrono::milliseconds(80));
    void swipe(const std::vector<Point>& points,
               std::chrono::milliseconds duration = std::chrono::milliseconds(300));
    void close() noexcept;

    [[nodiscard]] bool is_open() const noexcept { return fd_ >= 0; }
    [[nodiscard]] const Options& options() const noexcept { return options_; }

private:
    VirtualTouchDevice(int fd, Options options) noexcept;

    void emit(std::uint16_t type, std::uint16_t code, std::int32_t value);
    void sync();
    void set_position(Point point);
    void touch_down(Point point);
    void touch_move(Point point);
    void touch_up();
    void validate_point(Point point) const;

    int fd_ = -1;
    Options options_;
    bool touching_ = false;
    std::int32_t tracking_id_ = 1;
};

}  // namespace nier::uinput

