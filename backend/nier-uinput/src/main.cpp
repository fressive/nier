#include "nier/uinput_device.h"

#include <charconv>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

using nier::uinput::Point;
using nier::uinput::VirtualTouchDevice;

struct Arguments {
    VirtualTouchDevice::Options options;
    std::string command;
    std::vector<std::string> positional;
    std::int64_t duration_ms = 80;
    bool probe = false;
    bool serve = false;
};

void print_usage(std::ostream& out) {
    out << "Usage:\n"
        << "  nier-uinput probe [--device PATH]\n"
        << "  nier-uinput click --width W --height H X Y [--duration-ms N]\n"
        << "  nier-uinput swipe --width W --height H X1 Y1 X2 Y2 [X3 Y3 ...] [--duration-ms N]\n"
        << "  nier-uinput serve --width W --height H [--device PATH]\n\n"
        << "Options:\n"
        << "  --device PATH       uinput device (default: /dev/uinput)\n"
        << "  --name NAME         virtual device name\n"
        << "  --width N           screen width in pixels\n"
        << "  --height N          screen height in pixels\n"
        << "  --duration-ms N     click/swipe duration\n"
        << "  -h, --help          show this help\n";
}

template <typename Integer>
Integer parse_integer(std::string_view value, const char* label) {
    Integer result{};
    const auto* first = value.data();
    const auto* last = value.data() + value.size();
    const auto parsed = std::from_chars(first, last, result);
    if (parsed.ec != std::errc{} || parsed.ptr != last) {
        throw std::invalid_argument(std::string("invalid ") + label + ": " + std::string(value));
    }
    return result;
}

Arguments parse_arguments(int argc, char** argv) {
    Arguments result;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument(argv[index]);
        if (argument == "-h" || argument == "--help") {
            print_usage(std::cout);
            std::exit(0);
        }
        if (argument == "--device" || argument == "--name" || argument == "--width" ||
            argument == "--height" || argument == "--duration-ms") {
            if (index + 1 >= argc) throw std::invalid_argument("missing value for " + std::string(argument));
            const std::string_view value(argv[++index]);
            if (argument == "--device") result.options.path = value;
            else if (argument == "--name") result.options.name = value;
            else if (argument == "--width") result.options.width = parse_integer<std::int32_t>(value, "width");
            else if (argument == "--height") result.options.height = parse_integer<std::int32_t>(value, "height");
            else result.duration_ms = parse_integer<std::int64_t>(value, "duration-ms");
            continue;
        }
        if (result.command.empty() &&
            (argument == "probe" || argument == "click" || argument == "swipe" || argument == "serve")) {
            result.command = argument;
            result.probe = argument == "probe";
            result.serve = argument == "serve";
        } else {
            result.positional.emplace_back(argument);
        }
    }
    if (result.command.empty()) throw std::invalid_argument("missing command");
    return result;
}

Point parse_point(const std::vector<std::string>& values, std::size_t offset) {
    return Point{
        parse_integer<std::int32_t>(values[offset], "x coordinate"),
        parse_integer<std::int32_t>(values[offset + 1], "y coordinate"),
    };
}

std::string response_error(const std::exception& error) {
    std::string message = error.what();
    for (char& character : message) {
        if (character == '\n' || character == '\r') character = ' ';
    }
    return message;
}

void require_end(std::istringstream& stream) {
    std::string extra;
    if (stream >> extra) throw std::invalid_argument("unexpected argument: " + extra);
}

Point parse_server_point(std::istringstream& stream) {
    std::string x;
    std::string y;
    if (!(stream >> x >> y)) throw std::invalid_argument("point requires X Y");
    return Point{
        parse_integer<std::int32_t>(x, "x coordinate"),
        parse_integer<std::int32_t>(y, "y coordinate"),
    };
}

bool execute_server_command(std::string_view line, VirtualTouchDevice& device) {
    std::istringstream stream{std::string(line)};
    std::string command;
    if (!(stream >> command)) return false;

    if (command == "PING") {
        require_end(stream);
        return false;
    }
    if (command == "CLOSE") {
        require_end(stream);
        return true;
    }
    if (command == "CLICK") {
        const auto point = parse_server_point(stream);
        std::string duration_value;
        if (!(stream >> duration_value)) throw std::invalid_argument("click requires duration-ms");
        const auto duration = parse_integer<std::int64_t>(duration_value, "duration-ms");
        require_end(stream);
        device.click(point, std::chrono::milliseconds(duration));
        return false;
    }
    if (command == "SWIPE") {
        std::string duration_value;
        std::string count_value;
        if (!(stream >> duration_value >> count_value)) {
            throw std::invalid_argument("swipe requires duration-ms and point count");
        }
        const auto duration = parse_integer<std::int64_t>(duration_value, "duration-ms");
        const auto count = parse_integer<std::int32_t>(count_value, "point count");
        if (count < 2 || count > 4096) {
            throw std::invalid_argument("swipe point count must be between 2 and 4096");
        }
        std::vector<Point> points;
        points.reserve(static_cast<std::size_t>(count));
        for (std::int32_t index = 0; index < count; ++index) {
            points.push_back(parse_server_point(stream));
        }
        require_end(stream);
        device.swipe(points, std::chrono::milliseconds(duration));
        return false;
    }
    throw std::invalid_argument("unknown server command: " + command);
}

int run_server(const Arguments& arguments) {
    VirtualTouchDevice::validate_options(arguments.options);
    auto device = VirtualTouchDevice::create(arguments.options);
    std::cout << "READY\n" << std::flush;

    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            const bool close_requested = execute_server_command(line, device);
            std::cout << "OK\n" << std::flush;
            if (close_requested) return 0;
        } catch (const std::exception& error) {
            std::cout << "ERR " << response_error(error) << "\n" << std::flush;
            if (!device.is_open()) return 2;
        }
    }
    return 0;
}

int run(const Arguments& arguments) {
    if (arguments.probe) {
        std::cout << "root=" << (VirtualTouchDevice::is_root() ? "true" : "false") << '\n'
                  << "device=" << arguments.options.path << '\n'
                  << "writable=" << (VirtualTouchDevice::path_available(arguments.options.path) ? "true" : "false") << '\n'
                  << "persistent=true\n";
        return 0;
    }

    if (arguments.serve) return run_server(arguments);

    VirtualTouchDevice::validate_options(arguments.options);
    if (arguments.duration_ms < 0) throw std::invalid_argument("duration-ms must not be negative");
    auto device = VirtualTouchDevice::create(arguments.options);
    const auto duration = std::chrono::milliseconds(arguments.duration_ms);

    if (arguments.command == "click") {
        if (arguments.positional.size() != 2) throw std::invalid_argument("click requires X Y");
        device.click(parse_point(arguments.positional, 0), duration);
        return 0;
    }

    if (arguments.command == "swipe") {
        if (arguments.positional.size() < 4 || arguments.positional.size() % 2 != 0) {
            throw std::invalid_argument("swipe requires at least two X Y points");
        }
        std::vector<Point> points;
        points.reserve(arguments.positional.size() / 2);
        for (std::size_t index = 0; index < arguments.positional.size(); index += 2) {
            points.push_back(parse_point(arguments.positional, index));
        }
        if (arguments.duration_ms == 0) throw std::invalid_argument("swipe duration must be positive");
        device.swipe(points, duration);
        return 0;
    }
    throw std::invalid_argument("unknown command: " + arguments.command);
}

}  // namespace

int main(int argc, char** argv) {
    std::signal(SIGPIPE, SIG_IGN);
    try {
        return run(parse_arguments(argc, argv));
    } catch (const std::exception& error) {
        std::cerr << "nier-uinput: " << error.what() << '\n';
        std::cerr << "Use --help for usage.\n";
        return 2;
    }
}
