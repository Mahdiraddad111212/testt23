import asyncio
import logging
import os
import json # تم الإبقاء عليه جزئياً لكن لم يعد مستخدماً في منطق الأرصدة
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import requests
import base64
import textwrap

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import google.generativeai as genai

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# 💡 Configuration 💡
# ==============================================================================
# 1. تم تعديل التوكن
TELEGRAM_BOT_TOKEN = "8516911901:AAEm0dwHicVtY_1gdTivCsq6PD4hBPG7j4o"
GEMINI_API_KEY = "AIzaSyAwIcy_xQxJoMlo9BpX--17_4_av8qJl30"

# Forward targets
PERSONAL_ACCOUNT_ID = 7794213510 
# تم الإبقاء على معرف المجموعة كما هو
GROUP_ID = -1002790212538 

# --- Credit System Configuration (REMOVED) ---
# تم حذف جميع متغيرات إعدادات الرصيد
# ==============================================================================

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)


class MCQBot:
    def __init__(self):
        self.setup_font()


    def setup_font(self):
        """Setup font for image generation"""
        try:
            # Try to load a system font (Arial, DejaVu Sans, etc.)
            self.font_large = ImageFont.truetype("arial.ttf", 24)
            self.font_medium = ImageFont.truetype("arial.ttf", 20)
            self.font_small = ImageFont.truetype("arial.ttf", 16)
        except OSError:
            try:
                # Try alternative fonts
                self.font_large = ImageFont.truetype("DejaVuSans.ttf", 24)
                self.font_medium = ImageFont.truetype("DejaVuSans.ttf", 20)
                self.font_small = ImageFont.truetype("DejaVuSans.ttf", 16)
            except OSError:
                # Use default font if no system font available
                self.font_large = ImageFont.load_default()
                self.font_medium = ImageFont.load_default()
                self.font_small = ImageFont.load_default()

    def create_enhanced_prompt(self):
        """Create an optimized prompt for Gemini to extract all MCQs from the image accurately"""
        return """
You are an expert Multiple Choice Question (MCQ) analyzer.

Your task is to analyze the provided image containing a midical question extract ALL the MCQs it contains. For each MCQ, you MUST return:
1. Question number (e.g., 1, 2, 25, 30)
2. Full question text (translated to English if necessary)
3. All answer choices (labeled A, B, C, D, E, etc.)
4.Read the question from the image.
5.Solve it accurately using trusted sources.
6. The correct answer letter (A/B/C/D/E)

CRITICAL RULES:
- Extract every MCQ in the image (even if there are multiple questions).
- Translate the text to English if it's not already.
- Be extremely accurate and detailed.
- If the number of choices is not exactly 4, include all valid options (e.g., A to E).
- Maintain the structure and order exactly as shown.
- ALWAYS try to determine the correct answer based on your knowledge
- Only use UNCERTAIN if you absolutely cannot determine the answer

REQUIRED OUTPUT FORMAT FOR EACH QUESTION:
QUESTION_NUMBER: [number]
QUESTION_TEXT: [full question text in English]
ANSWER_CHOICES:
A) [text of choice A]
B) [text of choice B]
C) [text of choice C]
D) [text of choice D]
E) [text of choice E if exists]
CORRECT_ANSWER: [A/B/C/D/E based on your knowledge]

Note: Special sensory nerves are those that carry special sensory information like smell, vision, hearing, etc. These include:
Now analyze the image and return all MCQs using the exact format above.
"""

    def is_image_file(self, file_name, mime_type):
        """Check if the file is an image based on name and mime type"""
        if not file_name:
            return False
        
        # Check file extension
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif']
        file_extension = os.path.splitext(file_name.lower())[1]
        
        # Check mime type
        image_mime_types = ['image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp', 'image/tiff']
        
        return file_extension in image_extensions or mime_type in image_mime_types

    async def process_image_with_gemini(self, image_data):
        """Process image with Gemini"""
        try:
            logger.info("🔄 Starting Gemini request")
            
            # Convert image data to PIL Image
            image = Image.open(BytesIO(image_data))
            
            # Get the enhanced prompt
            prompt = self.create_enhanced_prompt()
            
            # Create model instance
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # Send request to Gemini
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.generate_content([prompt, image])
            )
            
            logger.info("✅ Gemini request completed")
            return response.text
            
        except Exception as e:
            logger.error(f"❌ Error processing image with Gemini: {e}")
            return None

    def parse_gemini_response(self, response_text):
        """Parse Gemini response to extract structured data"""
        try:
            lines = response_text.strip().split('\n')
            
            question_data = {
                'question_number': '',
                'question_text': '',
                'answer_choices': [],
                'correct_answer': ''
            }
            
            current_section = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if line.startswith('QUESTION_NUMBER:'):
                    question_data['question_number'] = line.split(':', 1)[1].strip()
                elif line.startswith('QUESTION_TEXT:'):
                    question_data['question_text'] = line.split(':', 1)[1].strip()
                elif line.startswith('ANSWER_CHOICES:'):
                    current_section = 'choices'
                elif line.startswith('CORRECT_ANSWER:'):
                    question_data['correct_answer'] = line.split(':', 1)[1].strip()
                elif current_section == 'choices':
                    # More flexible parsing for answer choices
                    if any(line.startswith(f"{letter})") for letter in ['A', 'B', 'C', 'D', 'E', 'F']):
                        question_data['answer_choices'].append(line)
                    elif line.startswith(('A)', 'B)', 'C)', 'D)', 'E)', 'F)')):
                        question_data['answer_choices'].append(line)
            
            return question_data
            
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return None

    # 2. تم تغيير الخلفية الافتراضية هنا
    def create_answer_image(self, question_data, background_filename="jj1.jpg"):
        """Create an image with the MCQ answer using background image"""
        try:
            # Load background image
            try:
                # استخدام background_filename المحدد
                background_image = Image.open(background_filename)
                bg_width, bg_height = background_image.size
            except FileNotFoundError:
                logger.warning(f"Background image '{background_filename}' not found. Creating default background.")
                bg_width, bg_height = 522, 294
                background_image = Image.new('RGB', (bg_width, bg_height), (255, 255, 224))
            
            # Create a copy to work with
            image = background_image.copy()
            draw = ImageDraw.Draw(image)
            
            # 4. تم تغيير لون الخط إلى الأسود (RGB: 0, 0, 0)
            text_color = (0, 0, 0) 
            
            # Calculate font sizes based on image size
            if bg_width > 500:
                header_size = 16
                question_size = 14
                choices_size = 13
                answer_size = 14
            else:
                header_size = 14
                question_size = 12
                choices_size = 11
                answer_size = 12
            
            try:
                header_font = ImageFont.truetype("arialbd.ttf", header_size)
                question_font = ImageFont.truetype("arial.ttf", question_size)
                choices_font = ImageFont.truetype("arial.ttf", choices_size)
                answer_font = ImageFont.truetype("arialbd.ttf", answer_size)
            except OSError:
                try:
                    header_font = ImageFont.truetype("arial.ttf", header_size)
                    question_font = ImageFont.truetype("arial.ttf", question_size)
                    choices_font = ImageFont.truetype("arial.ttf", choices_size)
                    answer_font = ImageFont.truetype("arial.ttf", answer_size)
                except OSError:
                    header_font = ImageFont.load_default()
                    question_font = ImageFont.load_default()
                    choices_font = ImageFont.load_default()
                    answer_font = ImageFont.load_default()
            
            # Define text positioning
            center_x = bg_width // 2
            start_y = int(bg_height * 0.12)
            line_spacing = int(header_size * 1.2)
            
            # Prepare text sections
            question_header = f"Question {question_data['question_number']}:"
            question_text = question_data['question_text']
            correct_answer_letter = question_data['correct_answer'].upper()
            answer_text = f"Answer: {correct_answer_letter}"
            
            current_y = start_y
            
            # 1. Draw question header (centered)
            header_bbox = draw.textbbox((0, 0), question_header, font=header_font)
            header_width = header_bbox[2] - header_bbox[0]
            header_x = center_x - (header_width // 2)
            draw.text((header_x, current_y), question_header, fill=text_color, font=header_font)
            current_y += int(line_spacing * 1.8)
            
            # 2. Draw question text (centered, with proper wrapping)
            available_width = int(bg_width * 0.85)
            avg_char_width = question_size * 0.6
            wrap_width = int(available_width / avg_char_width)
            
            question_lines = textwrap.wrap(question_text, width=wrap_width)
            for line in question_lines:
                line_bbox = draw.textbbox((0, 0), line, font=question_font)
                line_width = line_bbox[2] - line_bbox[0]
                line_x = center_x - (line_width // 2)
                draw.text((line_x, current_y), line, fill=text_color, font=question_font)
                current_y += int(line_spacing * 1.3)
            
            current_y += int(line_spacing * 0.7)
            
            # 3. Draw choices (left-aligned)
            choices_start_x = int(bg_width * 0.15)
            
            for choice in question_data['answer_choices']:
                draw.text((choices_start_x, current_y), choice, fill=text_color, font=choices_font)
                current_y += int(line_spacing * 1.2)
            
            current_y += int(line_spacing * 0.8)
            
            # 4. Draw answer (centered)
            answer_bbox = draw.textbbox((0, 0), answer_text, font=answer_font)
            answer_width = answer_bbox[2] - answer_bbox[0]
            answer_x = center_x - (answer_width // 2)
            draw.text((answer_x, current_y), answer_text, fill=text_color, font=answer_font)
            
            # Save image to BytesIO
            img_buffer = BytesIO()
            image.save(img_buffer, format='PNG', quality=95)
            img_buffer.seek(0)
            
            return img_buffer
            
        except Exception as e:
            logger.error(f"Error creating answer image: {e}")
            return None
        
    async def process_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id, file_name=None):
        """
        Process image message, solve it, and send the answer to the user 
        and forward to admin/group with specific backgrounds.
        """
        user_id = update.effective_user.id
        
        processing_msg = None 
        
        try:
            # Send processing message
            processing_msg = await update.message.reply_text("🔄 جاري معالجة الصورة...")
            
            # Get file and download image data
            file = await context.bot.get_file(file_id)
            image_data = await file.download_as_bytearray()
            
            # Process image with Gemini
            gemini_response = await self.process_image_with_gemini(image_data)
            
            if not gemini_response:
                await processing_msg.edit_text("❌ خطأ في معالجة الصورة: لم أتمكن من الحصول على رد من Gemini.")
                return
            
            # Parse response
            question_data = self.parse_gemini_response(gemini_response)
            
            if not question_data or not question_data['question_number']:
                await processing_msg.edit_text("❌ خطأ في معالجة الصورة: لم أتمكن من استخراج معلومات السؤال.")
                return
            
            # -----------------------------------------------------------
            # 🚀 منطق الإرسال المتعدد باستخدام خلفيات مختلفة (التعديلات المطلوبة في أسماء الملفات)
            # -----------------------------------------------------------

            user_answer_image = None
            
            # 3.1. إرسال الإجابة إلى المستخدم الأصلي (باستخدام الخلفية: jj1.jpg)
            user_answer_image = self.create_answer_image(question_data, "jj1.jpg")
            
            if user_answer_image:
                # Delete processing message first if the image is ready for user
                await processing_msg.delete() 
                processing_msg = None 
                
                await update.message.reply_photo(
                    photo=user_answer_image,
                    caption=f"✅ تم حل السؤال {question_data['question_number']}!\n🎯 الإجابة: **{question_data['correct_answer']}**",
                    parse_mode='Markdown'
                )
                logger.info("✅ Successfully sent to original user.")
            
            
            # 3.2. إرسال الإجابة إلى الحساب الشخصي (باستخدام خلفية mm.jpg)
            personal_image = self.create_answer_image(question_data, "mm1.jpg")
            if personal_image:
                try:
                    await context.bot.send_photo(
                        chat_id=PERSONAL_ACCOUNT_ID,
                        photo=personal_image,
                        caption=f"🎯 الإجابة: **{question_data['correct_answer']}**",
                        parse_mode='Markdown'
                    )
                    logger.info(f"✅ Successfully sent to personal account: {PERSONAL_ACCOUNT_ID}")
                except Exception as e:
                    logger.error(f"❌ Failed to send to personal account: {e}")

            # 3.3. إرسال الإجابة إلى المجموعة (باستخدام خلفية mm.jpg)
            group_image = self.create_answer_image(question_data, "mm1.jpg")
            if group_image:
                try:
                    await context.bot.send_photo(
                        chat_id=GROUP_ID,
                        photo=group_image,
                        caption=f"🎯 الإجابة: **{question_data['correct_answer']}**",
                        parse_mode='Markdown'
                    )
                    logger.info(f"✅ Successfully sent to group: {GROUP_ID}")
                except Exception as e:
                    logger.error(f"❌ Failed to send to group: {e}")
                    
            # -----------------------------------------------------------
            
            # في حال فشل إنشاء صورة المستخدم، نرسل رداً نصياً للمستخدم الأصلي ونحذف رسالة المعالجة
            if not user_answer_image:
                if processing_msg:
                    await processing_msg.delete()
                
                correct_answer_letter = question_data['correct_answer'].upper()
                await update.message.reply_text(
                    f"✅ **تم حل السؤال {question_data['question_number']}!**\n"
                    f"🎯 الإجابة: **{correct_answer_letter}**",
                    parse_mode='Markdown'
                )

        except Exception as e:
            logger.error(f"❌ Error processing image: {e}")
            if processing_msg:
                try:
                    await processing_msg.edit_text("❌ حدث خطأ غير متوقع أثناء معالجة الصورة.")
                except:
                    await update.message.reply_text("❌ حدث خطأ غير متوقع أثناء معالجة الصورة.")
            else:
                await update.message.reply_text("❌ حدث خطأ غير متوقع أثناء معالجة الصورة.")


    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages"""
        try:
            # Get the largest photo
            photo = update.message.photo[-1]
            await self.process_image(update, context, photo.file_id)
            
        except Exception as e:
            logger.error(f"Error handling photo: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء معالجة الصورة. يرجى المحاولة مرة أخرى.")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document messages (including image files)"""
        try:
            document = update.message.document
            
            # Check if the document is an image
            if not self.is_image_file(document.file_name, document.mime_type):
                await update.message.reply_text("❌ يرجى إرسال ملف صورة (JPG, PNG, GIF, إلخ) يحتوي على سؤال الاختيار المتعدد.")
                return
            
            # Check file size
            if document.file_size > 20 * 1024 * 1024: 
                await update.message.reply_text("❌ حجم الملف كبير جداً. يرجى إرسال صورة أصغر من 20MB.")
                return
            
            # Process the image document
            await self.process_image(update, context, document.file_id, document.file_name)
            
        except Exception as e:
            logger.error(f"Error handling document: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء معالجة المستند. يرجى المحاولة مرة أخرى.")

    # ==========================================================================
    # 💬 General Commands 
    # ==========================================================================
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        
        welcome_text = f"""
🤖 **بوت حل أسئلة الاختيار المتعدد - خدمة مجانية**

🎯 **المميزات:**
✅ حل أسئلة الاختيار المتعدد من الصور
✅ دعم جميع أنواع الصور

🔧 **الأوامر:**
• `/start` - رسالة الترحيب
• `/help` - التعليمات التفصيلية

**البوت الآن مجاني بالكامل!** أرسل صورة السؤال مباشرة. 🚀
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = f"""

📸 **الخطوات:**
1. **أرسل الصورة**: أرسل صورة تحتوي على سؤال اختيار متعدد.
2. **انتظر المعالجة**: سأقوم بتحليل الصورة.
3. **احصل على الإجابة**: ستحصل على الإجابة مع الشرح.

🎯 **أفضل الممارسات:**
• استخدم صوراً واضحة ومضيئة جيداً.
• تأكد من قابلية قراءة النص.

🔧 **الأوامر المفيدة:**
• `/help` - رسالة المساعدة هذه
• `/start` - رسالة الترحيب

جاهز للتجربة؟ أرسل لي صور أسئلة الاختيار المتعدد! 🚀
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')


def main():
    """Main function to run the bot"""
    # Create bot instance
    bot = MCQBot()
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    
    # --- Credit Management Commands (REMOVED) ---
    # ----------------------------------
    
    application.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    
    # Run the bot
    print("🚀 MCQ Solver Bot started! (FREE MODE)")
    print("💡 Ready to solve MCQ questions from images!")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("🛑 Bot is shutting down...")
    finally:
        print("✅ Bot shutdown complete.")

if __name__ == '__main__':
    main()
