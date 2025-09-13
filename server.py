import os
import csv
import base64
import mimetypes
import asyncio
import logging
import threading
import time
import subprocess
from typing import Optional, Tuple
from flask import Flask, request, jsonify
from WPP_Whatsapp import Create
import sentry_sdk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WhatsAppSender:
    def __init__(self, session_name="whatsapp_session"):
        self.session = session_name
        self.creator = None
        self.client = None
        self.initialized = False
        self.loop = None
        self.thread = None
        self._stop_event = threading.Event()
        self.video_caption = "🇸🇦✨ Celebrate Saudi National Day with your exclusive calligraphy masterpiece from the Live Calligraphy Videobooth! 🎉\n\nShare the pride and joy of this special moment, crafted just for you!\n \n With heartfelt vibes,\n The Live Calligraphy Video Booth Team\n 📷 Join the celebration: @far.j.ana | @kareemgraphy #SaudiNationalDay"
        self.video_dir = "./videos"
        self.image_dir = "./images"
        self.image_caption = "🇸🇦✨ Celebrate Saudi National Day with your exclusive calligraphy masterpiece from the Live Calligraphy Videobooth! 🎉\n\nShare the pride and joy of this special moment, crafted just for you!\n \n With heartfelt vibes,\n The Live Calligraphy Video Booth Team\n 📷 Join the celebration: @far.j.ana | @kareemgraphy #SaudiNationalDay"
        self.default_caption = "🇸🇦✨ Celebrate Saudi National Day with your exclusive calligraphy masterpiece from the Live Calligraphy Videobooth! 🎉\n\nShare the pride and joy of this special moment, crafted just for you!\n \n With heartfelt vibes,\n The Live Calligraphy Video Booth Team\n 📷 Join the celebration: @far.j.ana | @kareemgraphy #SaudiNationalDay"

    def _create_event_loop(self):
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        return self.loop

    def _run_async_in_thread(self, coro):
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
            logger.error(f"Error in async operation: {e}")
            return None

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    async def _initialize_async(self):
        if self.initialized:
            return
        try:
            logger.info("Initializing WhatsApp client...")
            self.creator = Create(session=self.session)
            self.client = self.creator.start()  # Adjust to await if start is async
            if self.creator.state != 'CONNECTED':
                raise Exception(f"Connection failed: {self.creator.state}")
            self.initialized = True
            logger.info("WhatsApp client initialized successfully")
        except asyncio.TimeoutError:
            raise Exception("Timeout initializing WhatsApp client - please scan QR code")
        except Exception as e:
            logger.error(f"Failed to initialize WhatsApp client: {str(e)}")
            raise Exception(f"Failed to initialize WhatsApp client: {str(e)}")

    def initialize(self):
        async def init_coro():
            await self._initialize_async()
        return self._run_async_in_thread(init_coro())

    def check_ffmpeg(self) -> bool:
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def convert_to_mp4(self, input_path: str, output_path: str) -> bool:
        if not self.check_ffmpeg():
            logger.warning("FFmpeg not installed. Run 'sudo pacman -S ffmpeg' to enable conversion.")
            return False
        try:
            subprocess.run([
                'ffmpeg', '-i', input_path, '-c:v', 'libx264', '-crf', '28',
                '-preset', 'fast', '-c:a', 'aac', '-b:a', '128k', output_path
            ], capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg conversion failed: {e.stderr.decode()}")
            return False

    def encode_video_to_base64(self, file_path: str, use_data_url: bool = True, convert: bool = False) -> Optional[Tuple[str, str]]:
        if not os.path.exists(file_path):
            logger.error(f"File not found at {file_path}")
            return None
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type or not mime_type.startswith('video/'):
            mime_type = 'video/mp4'
            logger.warning(f"Could not detect MIME type, using {mime_type}")
        working_path = file_path
        if convert and file_path.lower().endswith(('.mov', '.avi', '.mkv')):
            temp_path = f"{os.path.splitext(file_path)[0]}_converted.mp4"
            if self.convert_to_mp4(file_path, temp_path):
                working_path = temp_path
                mime_type = 'video/mp4'
                logger.info(f"Converted to {temp_path}")
            else:
                logger.warning("Continuing with original file due to conversion failure")
        file_size_mb = os.path.getsize(working_path) / (1024 * 1024)
        if file_size_mb > 50:
            logger.warning(f"File size ({file_size_mb:.2f}MB) exceeds WhatsApp's 50MB limit. Consider compressing.")
        try:
            with open(working_path, 'rb') as f:
                base64_bytes = base64.b64encode(f.read())
            base64_str = base64_bytes.decode('utf-8')
            if use_data_url:
                base64_str = f"data:{mime_type};base64,{base64_str}"
            if convert and working_path != file_path and os.path.exists(working_path):
                os.remove(working_path)
                logger.info(f"Cleaned up temporary file: {working_path}")
            return base64_str, mime_type
        except MemoryError:
            logger.error("File too large for base64 encoding. Try compressing with FFmpeg.")
            return None
        except Exception as e:
            logger.error(f"Error encoding file: {e}")
            return None

    async def _send_message_async(self, phone_number: str, message: str):
        try:
            if not self.initialized:
                raise Exception("WhatsApp client not initialized. Please call initialize() first.")
            if not phone_number or not message:
                return {'success': False, 'message': 'Phone number and message are required'}
            phone_number = phone_number.replace('+', '')
            logger.info(f"Sending message to {phone_number}: {message[:50]}...")
            result = self.client.sendText(phone_number, message)
            if result:
                logger.info(f"Message sent successfully to {phone_number}")
                return {'success': True, 'message': 'Message sent successfully'}
            else:
                logger.warning(f"Failed to send message to {phone_number}")
                return {'success': False, 'message': 'Failed to send message'}
        except Exception as e:
            logger.error(f"Error sending message to {phone_number}: {str(e)}")
            return {'success': False, 'message': f'Error: {str(e)}'}

    async def _send_video_file_async(self, phone_number: str, file_path: str):
        try:
            if not self.initialized:
                raise Exception("WhatsApp client not initialized. Please call initialize() first.")
            if not phone_number or not file_path:
                return {'success': False, 'message': 'Phone number and file path are required'}
            phone_number = phone_number.replace('+', '')
            chat_id = f"{phone_number}@c.us"
            logger.info(f"Sending file to {chat_id}: {file_path}...")
            base64_str, mime_type = self.encode_video_to_base64(file_path, use_data_url=True, convert=True)
            if not base64_str:
                return {'success': False, 'message': 'Failed to encode file to base64'}
            logger.info(f"Base64 string generated, MIME type: {mime_type}")
            result = self.client.sendFile(  # Removed await
                chat_id,
                base64_str,
                os.path.basename(file_path),
                self.video_caption
            )
            logger.info(f"sendFile result: {result}")
            if result and result.get('ack') in [1, 2, 3]:
                logger.info(f"File sent successfully to {phone_number}")
                return {'success': True, 'message': 'File sent successfully'}
            else:
                logger.warning(f"Failed to send file to {phone_number}: {result}")
                return {'success': False, 'message': f'Failed to send file: {result}'}
        except Exception as e:
            logger.error(f"Error sending file: {str(e)}")
            return {'success': False, 'message': f'Error: {str(e)}'}

    async def _send_image_file_async(self, phone_number: str, file_path: str):
        try:
            if not self.initialized:
                raise Exception("WhatsApp client not initialized. Please call initialize() first.")
            if not phone_number or not file_path:
                return {'success': False, 'message': 'Phone number and file path are required'}
            phone_number = phone_number.replace('+', '')
            chat_id = f"{phone_number}@c.us"
            logger.info(f"Sending file to {chat_id}: {file_path}...")

            result = self.client.sendImage( 
                chat_id,
                file_path,
                os.path.basename(file_path),
                self.image_caption
            )
            logger.info(f"sendFile result: {result}")
            if result and result.get('ack') in [1, 2, 3]:
                logger.info(f"File sent successfully to {phone_number}")
                return {'success': True, 'message': 'File sent successfully'}
            else:
                logger.warning(f"Failed to send file to {phone_number}: {result}")
                return {'success': False, 'message': f'Failed to send file: {result}'}
        except Exception as e:
            logger.error(f"Error sending file: {str(e)}")
            return {'success': False, 'message': f'Error: {str(e)}'}

    def send_message(self, phone_number: str, message: str) -> dict:
        async def send_coro():
            return await self._send_message_async(phone_number, message)
        result = self._run_async_in_thread(send_coro())
        return result if result else {'success': False, 'message': 'Timeout or error in message sending'}

    def send_video_file(self, phone_number: str, file_path: str) -> dict:
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
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
                logger.info(f"File sent successfully to {phone_number}")
                return result
            else:
                logger.warning(f"File sending failed, falling back to CSV: {result}")
                fallback_result = self.save_to_csv(phone_number, file_path)
                return {
                    'success': False,
                    'message': f"File sending failed: {result.get('message', 'Unknown error')}. Fallback: {fallback_result}"
                }
        except Exception as e:
            logger.error(f"Error in send_file: {str(e)}")
            fallback_result = self.save_to_csv(phone_number, file_path)
            return {
                'success': False,
                'message': f"Error sending file: {str(e)}. Fallback: {fallback_result}"
            }
            
    def send_image_file(self, phone_number: str, file_path: str) -> dict:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
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
                    logger.info(f"File sent successfully to {phone_number}")
                    return result
                else:
                    logger.warning(f"File sending failed, falling back to CSV: {result}")
                    fallback_result = self.save_to_csv(phone_number, file_path)
                    return {
                        'success': False,
                        'message': f"File sending failed: {result.get('message', 'Unknown error')}. Fallback: {fallback_result}"
                    }
            except Exception as e:
                logger.error(f"Error in send_file: {str(e)}")
                fallback_result = self.save_to_csv(phone_number, file_path)
                return {
                    'success': False,
                    'message': f"Error sending file: {str(e)}. Fallback: {fallback_result}"
                }

    def save_to_csv(self, phone_number: str, file_path: str) -> str:
            csv_file = "error_files.csv"
            headers = ['Phone Number', 'File Path']
            try:
                file_exists = os.path.isfile(csv_file)
                with open(csv_file, mode='a', newline='') as file:
                    writer = csv.writer(file)
                    if not file_exists:
                        writer.writerow(headers)
                    writer.writerow([phone_number, file_path])
                sentry_sdk.capture_message(f"Data successfully appended to {csv_file}", level="info")
                return f"Data successfully appended to {csv_file}"
            except Exception as e:
                sentry_sdk.capture_exception(e)
                return f"Failed to append to {csv_file}: {str(e)}"


    def close(self):
        try:
            if self.loop and self.loop.is_running():
                async def close_coro():
                    if self.client:
                        await self.client.close()
                        logger.info("WhatsApp client closed")
                future = asyncio.run_coroutine_threadsafe(close_coro(), self.loop)
                future.result(timeout=10.0)
            if self.thread and self.thread.is_alive():
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join(timeout=5)
        except Exception as e:
            logger.error(f"Error closing WhatsApp client: {str(e)}")

sentry_sdk.init(
    dsn="https://1633a41a7bdbd109b78e4c63916b9d3a@o1037254.ingest.us.sentry.io/4510005925707776",
    send_default_pii=True,
)

app = Flask(__name__)
whatsapp_sender = WhatsAppSender()

@app.route('/send_message', methods=['POST'])
def send_whatsapp_message():
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
        logger.error(f"Error in send_whatsapp_message: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/send_video_file', methods=['POST'])
def send_video_file():
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
        logger.error(f"Error in send_video_file: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500
    
@app.route('/send_image_file', methods=['POST'])
def send_image_file():
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
        logger.error(f"Error in send_image_file: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'whatsapp_initialized': whatsapp_sender.initialized
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'message': 'WhatsApp Sender API',
        'endpoints': {
            'send_message': 'POST /send_message - {"phone_number": "1234567890", "message": "Hello!"}',
            'send_file': 'POST /send_file - {"phone_number": "1234567890", "file_name": "/path/to/file"}',
            'health': 'GET /health',
            'initialize': 'POST /initialize'
        },
        'initialized': whatsapp_sender.initialized
    })

@app.route('/initialize', methods=['POST'])
def initialize_whatsapp():
    try:
        if whatsapp_sender.initialized:
            return jsonify({'success': True, 'message': 'Already initialized'})
        result = whatsapp_sender.initialize()
        return jsonify({'success': True, 'message': 'Initialization successful - scan QR code if prompted'})
    except Exception as e:
        logger.error(f"Error in initialize_whatsapp: {str(e)}")
        return jsonify({'success': False, 'message': f'Initialization error: {str(e)}'}), 500

if __name__ == '__main__':
    logger.info("Starting Flask app. Call POST /initialize to set up WhatsApp client.")
    try:
        app.run(debug=True, host='127.0.0.1', port=5000)
    finally:
        whatsapp_sender.close()