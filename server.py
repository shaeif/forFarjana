import os
import csv
import base64
import mimetypes
import asyncio
import threading
import time
import subprocess
from typing import Optional, Tuple, Dict
from flask import Flask, request, jsonify
from WPP_Whatsapp import Create
import sentry_sdk
from sentry_sdk import capture_message, capture_exception

# Initialize Sentry
sentry_sdk.init(
    dsn="https://1633a41a7bdbd109b78e4c63916b9d3a@o1037254.ingest.us.sentry.io/4510005925707776",
    send_default_pii=True,
    traces_sample_rate=1.0,
)

class WhatsAppSender:
    def __init__(self, session_name: str = "whatsapp_session"):
        self.session = session_name
        self.creator = None
        self.client = None
        self.initialized = False
        self.loop = None
        self.thread = None
        self._stop_event = threading.Event()
        self.video_caption = (
            "🇸🇦✨ Celebrate Saudi National Day with your exclusive calligraphy masterpiece "
            "from the Live Calligraphy Videobooth! 🎉\n\n"
            "Share the pride and joy of this special moment, crafted just for you!\n\n"
            "With heartfelt vibes,\nThe Live Calligraphy Video Booth Team\n"
            "📷 Join the celebration: @far.j.ana | @kareemgraphy #SaudiNationalDay"
        )
        self.image_caption = self.video_caption
        self.default_caption = self.video_caption
        self.video_dir = "./videos"
        self.image_dir = "./images"

    def _create_event_loop(self) -> asyncio.AbstractEventLoop:
        """Create and set up a new event loop if none exists."""
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        return self.loop

    def _run_async_in_thread(self, coro):
        """Run an async coroutine in a separate thread with timeout handling."""
        if self.thread is None or not self.thread.is_alive():
            self._create_event_loop()
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
        while self.loop is None or not self.loop.is_running():
            time.sleep(0.1)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=30.0)
        except Exception as e:
            capture_exception(e)
            return None

    def _run_loop(self):
        """Run the event loop indefinitely."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    async def _initialize_async(self):
        """Initialize WhatsApp client asynchronously."""
        if self.initialized:
            return
        try:
            capture_message("Initializing WhatsApp client...")
            self.creator = Create(session=self.session)
            self.client = self.creator.start()  # Adjust to await if start is async
            if self.creator.state != 'CONNECTED':
                raise Exception(f"Connection failed: {self.creator.state}")
            self.initialized = True
            capture_message("WhatsApp client initialized successfully", level="info")
        except asyncio.TimeoutError:
            raise Exception("Timeout initializing WhatsApp client - please scan QR code")
        except Exception as e:
            capture_exception(e)
            raise Exception(f"Failed to initialize WhatsApp client: {str(e)}")

    def initialize(self) -> Dict[str, any]:
        """Initialize WhatsApp client synchronously."""
        async def init_coro():
            await self._initialize_async()
        try:
            self._run_async_in_thread(init_coro())
            return {'success': True, 'message': 'Initialization successful'}
        except Exception as e:
            capture_exception(e)
            return {'success': False, 'message': f'Initialization failed: {str(e)}'}

    def check_ffmpeg(self) -> bool:
        """Check if FFmpeg is installed."""
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            capture_exception(e)
            capture_message("FFmpeg not installed. Run 'sudo pacman -S ffmpeg' to enable conversion.", level="warning")
            return False

    def convert_to_mp4(self, input_path: str, output_path: str) -> bool:
        """Convert video to MP4 using FFmpeg."""
        if not self.check_ffmpeg():
            return False
        try:
            subprocess.run([
                'ffmpeg', '-i', input_path, '-c:v', 'libx264', '-crf', '28',
                '-preset', 'fast', '-c:a', 'aac', '-b:a', '128k', output_path
            ], capture_output=True, check=True)
            capture_message(f"Converted video to {output_path}", level="info")
            return True
        except subprocess.CalledProcessError as e:
            capture_exception(e)
            return False

    def encode_video_to_base64(self, file_path: str, use_data_url: bool = True, convert: bool = False) -> Optional[Tuple[str, str]]:
        """Encode a video file to base64."""
        if not os.path.exists(file_path):
            capture_message(f"File not found at {file_path}", level="error")
            return None
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type or not mime_type.startswith('video/'):
            mime_type = 'video/mp4'
            capture_message(f"Could not detect MIME type, using {mime_type}", level="warning")
        working_path = file_path
        if convert and file_path.lower().endswith(('.mov', '.avi', '.mkv')):
            temp_path = f"{os.path.splitext(file_path)[0]}_converted.mp4"
            if self.convert_to_mp4(file_path, temp_path):
                working_path = temp_path
                mime_type = 'video/mp4'
                capture_message(f"Converted to {temp_path}", level="info")
            else:
                capture_message("Continuing with original file due to conversion failure", level="warning")
        file_size_mb = os.path.getsize(working_path) / (1024 * 1024)
        if file_size_mb > 50:
            capture_message(f"File size ({file_size_mb:.2f}MB) exceeds WhatsApp's 50MB limit.", level="warning")
        try:
            with open(working_path, 'rb') as f:
                base64_bytes = base64.b64encode(f.read())
            base64_str = base64_bytes.decode('utf-8')
            if use_data_url:
                base64_str = f"data:{mime_type};base64,{base64_str}"
            if convert and working_path != file_path and os.path.exists(working_path):
                os.remove(working_path)
                capture_message(f"Cleaned up temporary file: {working_path}", level="info")
            return base64_str, mime_type
        except MemoryError:
            capture_message("File too large for base64 encoding.", level="error")
            return None
        except Exception as e:
            capture_exception(e)
            return None

    async def _send_message_async(self, phone_number: str, message: str) -> Dict[str, any]:
        """Send a text message asynchronously."""
        try:
            if not self.initialized:
                raise Exception("WhatsApp client not initialized.")
            if not phone_number or not message:
                return {'success': False, 'message': 'Phone number and message are required'}
            phone_number = phone_number.replace('+', '')
            capture_message(f"Sending message to {phone_number}: {message[:50]}...", level="info")
            result = self.client.sendText(phone_number, message)
            if result:
                capture_message(f"Message sent successfully to {phone_number}", level="info")
                return {'success': True, 'message': 'Message sent successfully'}
            else:
                capture_message(f"Failed to send message to {phone_number}", level="warning")
                return {'success': False, 'message': 'Failed to send message'}
        except Exception as e:
            capture_exception(e)
            return {'success': False, 'message': f'Error: {str(e)}'}

    async def _send_video_file_async(self, phone_number: str, file_path: str) -> Dict[str, any]:
        """Send a video file asynchronously."""
        try:
            if not self.initialized:
                raise Exception("WhatsApp client not initialized.")
            if not phone_number or not file_path:
                return {'success': False, 'message': 'Phone number and file path are required'}
            phone_number = phone_number.replace('+', '')
            chat_id = f"{phone_number}@c.us"
            capture_message(f"Sending video to {chat_id}: {file_path}...", level="info")
            base64_str, mime_type = self.encode_video_to_base64(file_path, use_data_url=True, convert=True)
            if not base64_str:
                return {'success': False, 'message': 'Failed to encode file to base64'}
            result = self.client.sendFile(
                chat_id,
                base64_str,
                os.path.basename(file_path),
                self.video_caption
            )
            if result and result.get('ack') in [1, 2, 3]:
                capture_message(f"Video sent successfully to {phone_number}", level="info")
                return {'success': True, 'message': 'File sent successfully'}
            else:
                capture_message(f"Failed to send video to {phone_number}: {result}", level="warning")
                return {'success': False, 'message': f'Failed to send file: {result}'}
        except Exception as e:
            capture_exception(e)
            return {'success': False, 'message': f'Error: {str(e)}'}

    async def _send_image_file_async(self, phone_number: str, file_path: str) -> Dict[str, any]:
        """Send an image file asynchronously."""
        try:
            if not self.initialized:
                raise Exception("WhatsApp client not initialized.")
            if not phone_number or not file_path:
                return {'success': False, 'message': 'Phone number and file path are required'}
            phone_number = phone_number.replace('+', '')
            chat_id = f"{phone_number}@c.us"
            capture_message(f"Sending image to {chat_id}: {file_path}...", level="info")
            result = self.client.sendImage(
                chat_id,
                file_path,
                os.path.basename(file_path),
                self.image_caption
            )
            if result and result.get('ack') in [1, 2, 3]:
                capture_message(f"Image sent successfully to {phone_number}", level="info")
                return {'success': True, 'message': 'File sent successfully'}
            else:
                capture_message(f"Failed to send image to {phone_number}: {result}", level="warning")
                return {'success': False, 'message': f'Failed to send file: {result}'}
        except Exception as e:
            capture_exception(e)
            return {'success': False, 'message': f'Error: {str(e)}'}

    def send_message(self, phone_number: str, message: str) -> Dict[str, any]:
        """Send a text message synchronously."""
        async def send_coro():
            return await self._send_message_async(phone_number, message)
        result = self._run_async_in_thread(send_coro())
        return result if result else {'success': False, 'message': 'Timeout or error in message sending'}

    def send_video_file(self, phone_number: str, file_path: str) -> Dict[str, any]:
        """Send a video file synchronously with CSV fallback."""
        if not os.path.exists(file_path):
            capture_message(f"File not found: {file_path}", level="error")
            fallback_result = self.save_to_csv(phone_number, file_path)
            return {
                'success': False,
                'message': f'File not found: {file_path}. Fallback: {fallback_result}'
            }
        async def send_coro():
            return await self._send_video_file_async(phone_number, file_path)
        try:
            result = self._run_async_in_thread(send_coro())
            if result and result.get('success', False):
                return result
            else:
                fallback_result = self.save_to_csv(phone_number, file_path)
                return {
                    'success': False,
                    'message': f"File sending failed: {result.get('message', 'Unknown error')}. Fallback: {fallback_result}"
                }
        except Exception as e:
            capture_exception(e)
            fallback_result = self.save_to_csv(phone_number, file_path)
            return {
                'success': False,
                'message': f"Error sending file: {str(e)}. Fallback: {fallback_result}"
            }

    def send_image_file(self, phone_number: str, file_path: str) -> Dict[str, any]:
        """Send an image file synchronously with CSV fallback."""
        if not os.path.exists(file_path):
            capture_message(f"File not found: {file_path}", level="error")
            fallback_result = self.save_to_csv(phone_number, file_path)
            return {
                'success': False,
                'message': f'File not found: {file_path}. Fallback: {fallback_result}'
            }
        async def send_coro():
            return await self._send_image_file_async(phone_number, file_path)
        try:
            result = self._run_async_in_thread(send_coro())
            if result and result.get('success', False):
                return result
            else:
                fallback_result = self.save_to_csv(phone_number, file_path)
                return {
                    'success': False,
                    'message': f"File sending failed: {result.get('message', 'Unknown error')}. Fallback: {fallback_result}"
                }
        except Exception as e:
            capture_exception(e)
            fallback_result = self.save_to_csv(phone_number, file_path)
            return {
                'success': False,
                'message': f"Error sending file: {str(e)}. Fallback: {fallback_result}"
            }

    def save_to_csv(self, phone_number: str, file_path: str) -> str:
        """Save failed send attempts to a CSV file."""
        csv_file = "error_files.csv"
        headers = ['Phone Number', 'File Path']
        try:
            file_exists = os.path.isfile(csv_file)
            with open(csv_file, mode='a', newline='') as file:
                writer = csv.writer(file)
                if not file_exists:
                    writer.writerow(headers)
                writer.writerow([phone_number, file_path])
            capture_message(f"Data successfully appended to {csv_file}", level="info")
            return f"Data successfully appended to {csv_file}"
        except Exception as e:
            capture_exception(e)
            return f"Failed to append to {csv_file}: {str(e)}"

    def close(self):
        """Cleanly close the WhatsApp client and event loop."""
        try:
            if self.loop and self.loop.is_running():
                async def close_coro():
                    if self.client:
                        await self.client.close()
                        capture_message("WhatsApp client closed", level="info")
                future = asyncio.run_coroutine_threadsafe(close_coro(), self.loop)
                future.result(timeout=10.0)
            if self.thread and self.thread.is_alive():
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join(timeout=5)
        except Exception as e:
            capture_exception(e)

# Flask application setup
app = Flask(__name__)
whatsapp_sender = WhatsAppSender()

@app.route('/send_message', methods=['POST'])
def send_whatsapp_message():
    """API endpoint to send a WhatsApp text message."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        phone_number = data.get('phone_number')
        message = data.get('message')
        if not phone_number or not message:
            return jsonify({'success': False, 'message': 'phone_number and message are required'}), 400
        result = whatsapp_sender.send_message(phone_number, message)
        return jsonify(result)
    except Exception as e:
        capture_exception(e)
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/send_video_file', methods=['POST'])
def send_video_file():
    """API endpoint to send a WhatsApp video file."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        phone_number = data.get('phone_number')
        file_name = data.get('file_name')
        whatsapp_sender.video_caption = data.get('caption', whatsapp_sender.default_caption)
        if not phone_number or not file_name:
            return jsonify({'success': False, 'message': 'phone_number and file_name are required'}), 400
        file_path = os.path.join(whatsapp_sender.video_dir, file_name)
        result = whatsapp_sender.send_video_file(phone_number, file_path)
        return jsonify(result)
    except Exception as e:
        capture_exception(e)
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/send_image_file', methods=['POST'])
def send_image_file():
    """API endpoint to send a WhatsApp image file."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No JSON data provided'}), 400
        phone_number = data.get('phone_number')
        file_name = data.get('file_name')
        whatsapp_sender.image_caption = data.get('caption', whatsapp_sender.default_caption)
        if not phone_number or not file_name:
            return jsonify({'success': False, 'message': 'phone_number and file_name are required'}), 400
        file_path = os.path.join(whatsapp_sender.image_dir, file_name)
        result = whatsapp_sender.send_image_file(phone_number, file_path)
        return jsonify(result)
    except Exception as e:
        capture_exception(e)
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """API endpoint to check service health."""
    return jsonify({
        'status': 'healthy',
        'whatsapp_initialized': whatsapp_sender.initialized
    })

@app.route('/', methods=['GET'])
def home():
    """API root endpoint with available endpoints information."""
    return jsonify({
        'message': 'WhatsApp Sender API',
        'endpoints': {
            'send_message': 'POST /send_message - {"phone_number": "+97466549299", "message": "Hello!"}',
            'send_video_file': 'POST /send_video_file - {"phone_number": "+97466549299", "file_name": "video.mp4", "caption": "Optional caption"}',
            'send_image_file': 'POST /send_image_file - {"phone_number": "+97466549299", "file_name": "image.jpg", "caption": "Optional caption"}',
            'health': 'GET /health',
            'initialize': 'POST /initialize'
        },
        'initialized': whatsapp_sender.initialized
    })

@app.route('/initialize', methods=['POST'])
def initialize_whatsapp():
    """API endpoint to initialize WhatsApp client."""
    try:
        if whatsapp_sender.initialized:
            return jsonify({'success': True, 'message': 'Already initialized'})
        result = whatsapp_sender.initialize()
        return jsonify(result)
    except Exception as e:
        capture_exception(e)
        return jsonify({'success': False, 'message': f'Initialization error: {str(e)}'}), 500

if __name__ == '__main__':
    capture_message("Starting Flask app. Call POST /initialize to set up WhatsApp client.", level="info")
    try:
        app.run(debug=True, host='127.0.0.1', port=5000)
    finally:
        whatsapp_sender.close()