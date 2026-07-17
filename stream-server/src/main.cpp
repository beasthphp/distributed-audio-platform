#include "httplib.h"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <regex>
#include <string>

namespace fs = std::filesystem;

namespace
{

constexpr const char* SERVER_HOST = "127.0.0.1";
constexpr int SERVER_PORT = 8080;

bool is_valid_uuid(const std::string& value)
{
    static const std::regex uuid_pattern(
        R"(^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$)"
    );

    return std::regex_match(value, uuid_pattern);
}

fs::path get_audio_directory()
{
    const char* configured_directory =
        std::getenv("AUDIO_STORAGE_DIR");

    if (configured_directory == nullptr)
    {
        throw std::runtime_error(
            "AUDIO_STORAGE_DIR environment variable is not set."
        );
    }

    return fs::absolute(configured_directory).lexically_normal();
}

void send_json_error(
    httplib::Response& response,
    const int status_code,
    const std::string& message
)
{
    response.status = status_code;

    response.set_content(
        "{\"detail\":\"" + message + "\"}",
        "application/json"
    );
}

} // namespace

int main()
{
    fs::path audio_directory;

    try
    {
        audio_directory = get_audio_directory();
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }

    if (!fs::exists(audio_directory) ||
        !fs::is_directory(audio_directory))
    {
        std::cerr
            << "Audio directory does not exist:\n"
            << audio_directory
            << '\n';

        return 1;
    }

    httplib::Server server;

    server.Get(
        "/health",
        [](const httplib::Request&, httplib::Response& response)
        {
            response.set_content(
                R"({"service":"stream-server","status":"healthy"})",
                "application/json"
            );
        }
    );

    server.Get(
        R"(/api/v1/audio/([0-9a-fA-F-]+)/stream)",
        [audio_directory](
            const httplib::Request& request,
            httplib::Response& response
        )
        {
            const std::string audio_id =
                request.matches[1].str();

            if (!is_valid_uuid(audio_id))
            {
                send_json_error(
                    response,
                    400,
                    "The audio ID is not a valid UUID."
                );

                return;
            }

            const fs::path audio_path =
                audio_directory / (audio_id + ".mp3");

            if (!fs::is_regular_file(audio_path))
            {
                send_json_error(
                    response,
                    404,
                    "Audio file was not found."
                );

                return;
            }

            response.set_header("Accept-Ranges", "bytes");
            response.set_header("Cache-Control", "no-store");

            response.set_file_content(
              audio_path.string(),
              "audio/mpeg"
            );

            std::cout
                << "Serving audio: "
                << audio_id
                << '\n';
        }
    );

    std::cout
        << "C++ audio stream server started\n"
        << "Storage: " << audio_directory << '\n'
        << "Listening: http://"
        << SERVER_HOST
        << ':'
        << SERVER_PORT
        << '\n';

    if (!server.listen(SERVER_HOST, SERVER_PORT))
    {
        std::cerr
            << "Could not listen on port "
            << SERVER_PORT
            << '\n';

        return 1;
    }

    return 0;
}