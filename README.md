# WhatsApp Sender API

## Overview

This is a Flask-based API for sending WhatsApp messages, images, and videos programmatically. It uses the `WPP_Whatsapp` library (a Python wrapper for WhatsApp Web) to handle WhatsApp interactions. The API supports asynchronous operations via threading and asyncio, video conversion using FFmpeg, and error tracking with Sentry. It's designed for scenarios like event photo booths (e.g., sending personalized videos/images for Saudi National Day celebrations).

Key features include:
- Text message sending
- Image and video file sending with customizable captions
- Automatic video format conversion (MOV/AVI/MKV to MP4) using FFmpeg
- Fallback to CSV logging for failed sends
- Health checks and initialization endpoints
- Sentry integration for monitoring and error reporting

The default captions are themed around Saudi National Day, but they can be overridden per request.

## Features

- **Message Types**: Text, images (JPEG/PNG), videos (MP4, with conversion support)
- **File Handling**: Base64 encoding for videos; direct file paths for images
- **Error Resilience**: Failed sends are logged to `error_files.csv` with phone number and file path
- **Monitoring**: Full Sentry integration for exceptions, messages, and performance traces
- **Async Support**: Threaded execution for non-blocking operations
- **Security**: PII-enabled Sentry for user context (phone numbers)

## Prerequisites

- Python 3.8+ (tested with 3.12)
- FFmpeg installed (for video conversion; optional but recommended)
  - On Arch Linux: `sudo pacman -S ffmpeg`
  - On Ubuntu: `sudo apt update && sudo apt install ffmpeg`
  - On macOS: `brew install ffmpeg`
- WhatsApp Web session (QR code scan required on first init)
- Sentry account (optional; uses provided DSN by default)

## Installation

1. **Clone or Download the Code**:
   ```
   git clone <your-repo-url>
   cd whatsapp-sender-api
   ```

2. **Set Up Virtual Environment**:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```
   pip install flask WPP_Whatsapp sentry-sdk
   ```
   - `WPP_Whatsapp`: Install via `pip install WPP_Whatsapp` (may require Node.js for underlying whatsapp-web.js)
   - Note: If `WPP_Whatsapp` installation fails, ensure Node.js is installed and check the library's docs for setup.

4. **Configure Sentry (Optional)**:
   - Replace the DSN in the code with your own: `sentry_sdk.init(dsn="your-dsn-here")`
   - For production, set `send_default_pii=False` to avoid logging sensitive data.

5. **Prepare Directories**:
   ```
   mkdir -p videos images
   ```
   - Place image files in `./images/` and video files in `./videos/`.

## Usage

1. **Start the Server**:
   ```
   python app.py
   ```
   - The app runs on `http://127.0.0.1:5000` in debug mode.

2. **Initialize WhatsApp Client**:
   - Send a POST to `/initialize` (one-time setup; scans QR code in console/browser).
   ```
   curl -X POST http://127.0.0.1:5000/initialize
   ```

3. **Send Messages/Files**:
   Use the API endpoints below. Phone numbers should be in international format (e.g., `+97466549299`).

### API Endpoints

| Endpoint              | Method | Description | Request Body Example |
|-----------------------|--------|-------------|----------------------|
| `/`                   | GET    | Home page with endpoint info | N/A |
| `/initialize`         | POST   | Initialize WhatsApp session | `{}` |
| `/send_message`       | POST   | Send text message | `{"phone_number": "+97466549299", "message": "Hello!"}` |
| `/send_video_file`    | POST   | Send video from `./videos/` | `{"phone_number": "+97466549299", "file_name": "video.mp4", "caption": "Custom caption"}` |
| `/send_image_file`    | POST   | Send image from `./images/` | `{"phone_number": "+97466549299", "file_name": "image.jpg", "caption": "Custom caption"}` |
| `/health`             | GET    | Health check (includes init status) | N/A |

- **Response Format**: All endpoints return JSON like `{"success": true, "message": "Success"}`.
- **File Size Limit**: Videos >50MB are warned (WhatsApp limit); compress if needed.
- **Fallback**: Failed sends append to `error_files.csv`.

Example with `curl`:
```
curl -X POST http://127.0.0.1:5000/send_video_file \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+97466549299", "file_name": "demo.mp4"}'
```

## Configuration

- **Session Name**: Change in `WhatsAppSender(session_name="custom_session")`.
- **Directories**: Update `video_dir` and `image_dir` in `__init__`.
- **Default Captions**: Modify `video_caption`/`image_caption` for custom defaults.
- **FFmpeg**: Disabled if not installed; videos won't convert.
- **Timeouts**: 30s for async ops; adjust in `_run_async_in_thread`.

## Error Handling

- **Common Errors**:
  - "WhatsApp client not initialized": Call `/initialize` first.
  - "File not found": Ensure files exist in `./videos/` or `./images/`.
  - QR Code: Scan via browser on first init.
- **Sentry**: All exceptions are captured; check your Sentry dashboard for traces.
- **CSV Fallback**: Failed sends log to `error_files.csv` for retry.

## Troubleshooting

- **QR Code Issues**: Restart and re-init; ensure no browser conflicts.
- **Library Errors**: Verify `WPP_Whatsapp` setup (may need Chrome/Puppeteer).
- **Port Conflicts**: Change `port=5000` in `app.run()`.
- **Video Conversion Fails**: Install FFmpeg and check permissions.
- **Large Files**: Use FFmpeg externally: `ffmpeg -i input.mov -vcodec libx264 output.mp4`.

## Contributing

1. Fork the repo.
2. Create a feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with Flask and WPP_Whatsapp.
- Error monitoring powered by Sentry.
- Inspired by event booth automation for Saudi National Day celebrations.

---

*Last updated: September 14, 2025*