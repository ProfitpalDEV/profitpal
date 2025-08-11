# email_manager.py - Отдельный модуль для email рассылок

import smtplib
import os
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from datetime import datetime, timedelta
from typing import List, Dict
from customer_manager import customer_manager

class EmailManager:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.sender_email = "denava.business@gmail.com"
        self.sender_password = os.getenv('GMAIL_APP_PASSWORD')  # App-specific password

    def create_price_change_email(self, new_monthly_price: float, effective_date: str) -> str:
        """Создание HTML письма об изменении цен"""
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #0a0e27; color: white; margin: 0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, rgba(30, 58, 95, 0.4), rgba(15, 35, 65, 0.6)); padding: 40px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.1);">

                <div style="text-align: center; margin-bottom: 30px;">
                    <div style="font-size: 28px; font-weight: 900; background: linear-gradient(135deg, #32cd32, #ffd700); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px;">💎 ProfitPal</div>
                </div>

                <h1 style="color: #ffd700; text-align: center; margin-bottom: 30px;">Important Pricing Update</h1>

                <p style="line-height: 1.6; margin-bottom: 20px;">Dear Valued ProfitPal Customer,</p>

                <p style="line-height: 1.6; margin-bottom: 25px;">We hope you've been enjoying unlimited stock analysis with ProfitPal! We're writing to inform you about an upcoming adjustment to our monthly subscription pricing.</p>

                <div style="background: rgba(50, 205, 50, 0.1); padding: 25px; border-radius: 15px; border-left: 4px solid #32cd32; margin: 25px 0;">
                    <h3 style="color: #32cd32; margin-bottom: 15px;">📋 What's Changing:</h3>
                    <ul style="line-height: 1.8; padding-left: 20px;">
                        <li><strong>Your Setup Fee:</strong> No change - $24.99 (already paid) ✅</li>
                        <li><strong>New Monthly Rate:</strong> ${new_monthly_price}/month (was $4.99)</li>
                        <li><strong>Effective Date:</strong> {effective_date} (30 days notice)</li>
                        <li><strong>Your Access:</strong> Continues uninterrupted</li>
                    </ul>
                </div>

                <div style="background: rgba(255, 215, 0, 0.1); padding: 25px; border-radius: 15px; border-left: 4px solid #ffd700; margin: 25px 0;">
                    <h3 style="color: #ffd700; margin-bottom: 15px;">🎯 Your Options:</h3>
                    <ul style="line-height: 1.8; padding-left: 20px;">
                        <li><strong>Continue Service:</strong> Keep enjoying unlimited analysis</li>
                        <li><strong>Cancel Anytime:</strong> Cancel before {effective_date} if needed</li>
                        <li><strong>Grandfather Protection:</strong> Your $24.99 setup remains forever</li>
                    </ul>
                </div>

                <div style="background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 15px; margin: 25px 0;">
                    <h3 style="color: #32cd32; margin-bottom: 15px;">🚀 Why This Change?</h3>
                    <p style="line-height: 1.6; margin-bottom: 15px;">Over the past year, we've:</p>
                    <ul style="line-height: 1.8; padding-left: 20px;">
                        <li>Added advanced AI analysis features</li>
                        <li>Improved real-time data accuracy</li>
                        <li>Enhanced server infrastructure</li>
                        <li>Expanded market coverage</li>
                    </ul>
                    <p style="line-height: 1.6; margin-top: 15px;">Rising data costs and continued platform improvements require this adjustment to maintain the high-quality service you expect.</p>
                </div>

                <div style="text-align: center; margin: 40px 0;">
                    <a href="https://profitpal.org/analysis" style="background: linear-gradient(135deg, #32cd32, #228b22); color: white; padding: 15px 30px; text-decoration: none; border-radius: 12px; font-weight: 600; display: inline-block; margin: 10px;">🔍 Continue Analysis</a>
                    <a href="https://profitpal.org/account" style="background: linear-gradient(135deg, #0a0e27, #1a1e3a); color: #32cd32; border: 2px solid #32cd32; padding: 15px 30px; text-decoration: none; border-radius: 12px; font-weight: 600; display: inline-block; margin: 10px;">⚙️ Manage Account</a>
                </div>

                <div style="border-top: 1px solid rgba(255, 255, 255, 0.1); padding-top: 25px; margin-top: 30px;">
                    <p style="line-height: 1.6; margin-bottom: 15px;">Questions or concerns? Simply reply to this email - we read every message personally.</p>
                    <p style="line-height: 1.6; margin-bottom: 20px;"><strong>Contact:</strong> denava.business@gmail.com</p>
                </div>

                <div style="text-align: center; color: #95a5a6; font-size: 14px; margin-top: 30px;">
                    <p>Thank you for being a valued ProfitPal customer!</p>
                    <p style="margin-top: 15px;">
                        Best regards,<br>
                        <strong style="color: #32cd32;">The ProfitPal Team</strong><br>
                        Denava OÜ
                    </p>
                    <p style="margin-top: 20px; font-size: 12px;">
                        This email was sent to notify you of pricing changes as outlined in our Terms of Service.<br>
                        ProfitPal is a product of Denava OÜ (Estonia)
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

    def send_mass_price_notification(self, new_monthly_price: float, effective_date: str) -> Dict:
        """Массовая рассылка уведомлений об изменении цен"""
        customers = customer_manager.get_all_active_customers()

        if not self.sender_password:
            print("❌ Gmail App Password not configured!")
            return {"success": False, "error": "Email credentials not configured"}

        email_content = self.create_price_change_email(new_monthly_price, effective_date)

        successful_sends = 0
        failed_sends = 0
        failed_emails = []

        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)

            for customer in customers:
                try:
                    msg = MimeMultipart('alternative')
                    msg['Subject'] = f"🔔 ProfitPal Price Update - Effective {effective_date}"
                    msg['From'] = f"ProfitPal Team <{self.sender_email}>"
                    msg['To'] = customer['email']

                    html_part = MimeText(email_content, 'html')
                    msg.attach(html_part)

                    server.send_message(msg)
                    successful_sends += 1

                    # Обновляем дату последнего уведомления
                    self.update_customer_notification(customer['id'])

                    print(f"✅ Sent to: {customer['email']}")

                except Exception as e:
                    failed_sends += 1
                    failed_emails.append(customer['email'])
                    print(f"❌ Failed to send to {customer['email']}: {e}")

            server.quit()

            # Сохраняем статистику
            self.save_notification_stats(
                old_price=4.99,
                new_price=new_monthly_price,
                customers_notified=successful_sends,
                effective_date=effective_date
            )

            result = {
                "success": True,
                "total_customers": len(customers),
                "successful_sends": successful_sends,
                "failed_sends": failed_sends,
                "failed_emails": failed_emails,
                "new_price": new_monthly_price,
                "effective_date": effective_date
            }

            print(f"📊 Mass notification complete:")
            print(f"   ✅ Successful: {successful_sends}")
            print(f"   ❌ Failed: {failed_sends}")
            print(f"   📅 Effective: {effective_date}")

            return result

        except Exception as e:
            print(f"❌ SMTP Connection Error: {e}")
            return {"success": False, "error": str(e)}

    def update_customer_notification(self, customer_id: int):
        """Обновление даты последнего уведомления клиента"""
        import sqlite3

        conn = sqlite3.connect(customer_manager.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE customers 
            SET last_notification = ? 
            WHERE id = ?
        ''', (datetime.now().isoformat(), customer_id))

        conn.commit()
        conn.close()

    def save_notification_stats(self, old_price: float, new_price: float, 
                              customers_notified: int, effective_date: str):
        """Сохранение статистики уведомлений"""
        import sqlite3

        conn = sqlite3.connect(customer_manager.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO price_notifications 
            (notification_date, old_price, new_price, customers_notified, effective_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), old_price, new_price, customers_notified, effective_date))

        conn.commit()
        conn.close()

# Глобальный экземпляр email менеджера  
email_manager = EmailManager()

# Простые функции для использования
def send_price_change_notification(new_monthly_price: float, days_notice: int = 30):
    """Отправка уведомления об изменении цен с указанием дней до введения"""
    effective_date = (datetime.now() + timedelta(days=days_notice)).strftime("%B %d, %Y")
    return email_manager.send_mass_price_notification(new_monthly_price, effective_date)

def get_notification_preview(new_monthly_price: float = 9.99):
    """Получение превью email для тестирования"""
    effective_date = (datetime.now() + timedelta(days=30)).strftime("%B %d, %Y")
    return email_manager.create_price_change_email(new_monthly_price, effective_date)


# Использование в командной строке
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "preview":
            # Показать превью письма
            print("📧 Email Preview:")
            print(get_notification_preview())

        elif sys.argv[1] == "send" and len(sys.argv) > 2:
            # Отправить уведомление
            new_price = float(sys.argv[2])
            result = send_price_change_notification(new_price)
            print(f"📊 Result: {result}")

        elif sys.argv[1] == "stats":
            # Показать статистику
            stats = customer_manager.get_customer_stats()
            print(f"📊 Customer Stats: {stats}")

    else:
        print("Usage:")
        print("  python email_manager.py preview")
        print("  python email_manager.py send 9.99")
        print("  python email_manager.py stats")