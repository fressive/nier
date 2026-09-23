#include "nier/uinput_device.h"

#include <cassert>
#include <stdexcept>

using nier::uinput::Point;
using nier::uinput::VirtualTouchDevice;

int main() {
    VirtualTouchDevice::Options options;
    options.width = 1080;
    options.height = 1920;

    assert(VirtualTouchDevice::point_in_bounds(options, Point{0, 0}));
    assert(VirtualTouchDevice::point_in_bounds(options, Point{1079, 1919}));
    assert(!VirtualTouchDevice::point_in_bounds(options, Point{-1, 0}));
    assert(!VirtualTouchDevice::point_in_bounds(options, Point{1080, 0}));
    assert(!VirtualTouchDevice::point_in_bounds(options, Point{0, 1920}));

    VirtualTouchDevice::validate_options(options);
    bool rejected = false;
    try {
        VirtualTouchDevice::validate_options(VirtualTouchDevice::Options{});
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);

    rejected = false;
    try {
        auto invalid = options;
        invalid.name = std::string(80, 'x');
        VirtualTouchDevice::validate_options(invalid);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
    return 0;
}

