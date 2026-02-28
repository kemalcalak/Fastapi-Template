from app.schemas.user import Language


def generate_password_reset_email(
    reset_link: str, project_name: str, lang: str = Language.EN
) -> dict[str, str]:
    """
    Generate subject, HTML, and plain text for password reset email.
    """
    if lang == Language.TR:
        subject = "Parola Sıfırlama İsteği"
        greeting = "Selam,"
        message = "Hesabınız için şifre sıfırlama talebinde bulundunuz. Aşağıdaki butona tıklayarak güvenli bir şekilde yeni şifrenizi belirleyebilirsiniz."
        btn_text = "Şifremi Sıfırla"
        link_issue_text = "Butona tıklamakta sorun mu yaşıyorsunuz? Aşağıdaki bağlantıyı tarayıcınıza kopyalayıp yapıştırabilirsiniz:"
        disclaimer = "Eğer bu talebi siz yapmadıysanız, bu e-postayı güvenle görmezden gelebilirsiniz. Güvenliğiniz için bu bağlantı 24 saat içinde geçersiz olacaktır."
        footer_text = f"&copy; {project_name}. Tüm hakları saklıdır."
        plain_text = f"Lütfen bağlantıya tıklayarak parolanızı sıfırlayın: {reset_link}"
    else:
        subject = "Password Reset Request"
        greeting = "Hi there,"
        message = "We received a request to reset your password. Click the button below to choose a new one safely."
        btn_text = "Reset Password"
        link_issue_text = "Having trouble with the button? Copy and paste the link below into your browser:"
        disclaimer = "If you didn't request a password reset, you can safely ignore this email. For your security, this link will expire in 24 hours."
        footer_text = f"&copy; {project_name}. All rights reserved."
        plain_text = f"Please reset your password by clicking on the link: {reset_link}"

    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{subject}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
        @media only screen and (max-width: 620px) {{
            .wrapper {{ padding: 20px !important; }}
            .container {{ width: 100% !important; border-radius: 12px !important; overflow: hidden; }}
            .content {{ padding: 32px 24px !important; }}
            .header {{ padding: 32px 24px !important; }}
        }}
    </style>
</head>
<body style="margin:0;padding:0;background-color:#f8fafc;-webkit-font-smoothing:antialiased;">
    <table class="wrapper" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc;padding:48px 0;">
        <tr>
            <td align="center">
                <table class="container" width="600" cellpadding="0" cellspacing="0" style="width:600px;background-color:#ffffff;border:1px solid #e2e8f0;border-radius:16px;box-shadow:0 10px 15px -3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td class="header" style="background-color:#ffffff;padding:40px 48px;border-bottom:1px solid #f1f5f9;text-align:center;">
                            <div style="display:inline-block;padding:12px;background-color:#eff6ff;border-radius:12px;margin-bottom:16px;">
                                <span style="font-size:32px;">🔐</span>
                            </div>
                            <h1 style="margin:0;font-size:24px;font-weight:700;color:#1e293b;letter-spacing:-0.5px;">{project_name}</h1>
                        </td>
                    </tr>
                    <!-- Main Body -->
                    <tr>
                        <td class="content" style="padding:40px 48px;">
                            <p style="margin:0 0 16px;font-size:16px;font-weight:600;color:#0f172a;">{greeting}</p>
                            <p style="margin:0 0 32px;font-size:16px;line-height:1.6;color:#475569;">{message}</p>
                            
                            <!-- Button CTA -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <a href="{reset_link}" style="display:inline-block;background-color:#2563eb;color:#ffffff;text-decoration:none;padding:14px 40px;border-radius:10px;font-size:16px;font-weight:600;box-shadow:0 4px 6px -1px rgba(37,99,235,0.2);">
                                            {btn_text}
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <div style="margin:40px 0;border-top:1px solid #f1f5f9;"></div>

                            <!-- Text Link Issue -->
                            <p style="margin:0 0 12px;font-size:14px;color:#64748b;">{link_issue_text}</p>
                            <p style="margin:0 0 32px;font-size:13px;word-break:break-all;line-height:1.5;">
                                <a href="{reset_link}" style="color:#2563eb;text-decoration:underline;">{reset_link}</a>
                            </p>

                            <div style="padding:20px;background-color:#f8fafc;border-radius:12px;border-left:4px solid #e2e8f0;">
                                <p style="margin:0;font-size:13px;line-height:1.6;color:#64748b;font-style:italic;">{disclaimer}</p>
                            </div>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding:32px 48px;background-color:#f8fafc;text-align:center;border-top:1px solid #e2e8f0;">
                            <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">{project_name}</p>
                            <p style="margin:0;font-size:12px;color:#94a3b8;">{footer_text}</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

    return {"subject": subject, "html": html, "plain_text": plain_text}


def generate_email_verification_email(
    verify_link: str, project_name: str, lang: str = Language.EN
) -> dict[str, str]:
    """
    Generate subject, HTML, and plain text for email verification.
    """
    if lang == Language.TR:
        subject = "E-postanızı Doğrulayın"
        greeting = "Hoş geldin!"
        message = "Kaydolduğunuz için çok mutluyuz. Hesabınızı aktifleştirmek ve e-posta adresinizi doğrulamak için lütfen aşağıdaki butona tıklayın."
        btn_text = "E-postamı Doğrula"
        link_issue_text = "Buton çalışmıyor mu? Bu bağlantıyı doğrudan tarayıcınıza kopyalayabilirsiniz:"
        disclaimer = "Eğer bu hesabı siz oluşturmadıysanız, bu e-postayı güvenle silebilirsiniz. Herhangi bir işlem yapmanıza gerek yoktur."
        footer_text = f"&copy; {project_name}. Tüm hakları saklıdır."
        plain_text = (
            f"Lütfen bağlantıya tıklayarak e-postanızı doğrulayın: {verify_link}"
        )
    else:
        subject = "Verify Your Email"
        greeting = "Welcome aboard!"
        message = "We're excited to have you join us. Please verify your email address by clicking the button below to get started."
        btn_text = "Verify Email"
        link_issue_text = (
            "Button not working? Copy and paste this link into your browser:"
        )
        disclaimer = "If you didn't create an account, you can safely ignore this email. No further action is required."
        footer_text = f"&copy; {project_name}. All rights reserved."
        plain_text = f"Please verify your email by clicking on the link: {verify_link}"

    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{subject}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
        @media only screen and (max-width: 620px) {{
            .wrapper {{ padding: 20px !important; }}
            .container {{ width: 100% !important; border-radius: 12px !important; overflow: hidden; }}
            .content {{ padding: 32px 24px !important; }}
            .header {{ padding: 32px 24px !important; }}
        }}
    </style>
</head>
<body style="margin:0;padding:0;background-color:#f8fafc;-webkit-font-smoothing:antialiased;">
    <table class="wrapper" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc;padding:48px 0;">
        <tr>
            <td align="center">
                <table class="container" width="600" cellpadding="0" cellspacing="0" style="width:600px;background-color:#ffffff;border:1px solid #e2e8f0;border-radius:16px;box-shadow:0 10px 15px -3px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <tr>
                        <td class="header" style="background-color:#ffffff;padding:40px 48px;border-bottom:1px solid #f1f5f9;text-align:center;">
                            <div style="display:inline-block;padding:12px;background-color:#ecfdf5;border-radius:12px;margin-bottom:16px;">
                                <span style="font-size:32px;">👋</span>
                            </div>
                            <h1 style="margin:0;font-size:24px;font-weight:700;color:#1e293b;letter-spacing:-0.5px;">{project_name}</h1>
                        </td>
                    </tr>
                    <!-- Main Body -->
                    <tr>
                        <td class="content" style="padding:40px 48px;">
                            <p style="margin:0 0 16px;font-size:16px;font-weight:600;color:#0f172a;">{greeting}</p>
                            <p style="margin:0 0 32px;font-size:16px;line-height:1.6;color:#475569;">{message}</p>
                            
                            <!-- Button CTA -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <a href="{verify_link}" style="display:inline-block;background-color:#10b981;color:#ffffff;text-decoration:none;padding:14px 40px;border-radius:10px;font-size:16px;font-weight:600;box-shadow:0 4px 6px -1px rgba(16,185,129,0.2);">
                                            {btn_text}
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <div style="margin:40px 0;border-top:1px solid #f1f5f9;"></div>

                            <!-- Text Link Issue -->
                            <p style="margin:0 0 12px;font-size:14px;color:#64748b;">{link_issue_text}</p>
                            <p style="margin:0 0 32px;font-size:13px;word-break:break-all;line-height:1.5;">
                                <a href="{verify_link}" style="color:#10b981;text-decoration:underline;">{verify_link}</a>
                            </p>

                            <div style="padding:20px;background-color:#f8fafc;border-radius:12px;border-left:4px solid #e2e8f0;">
                                <p style="margin:0;font-size:13px;line-height:1.6;color:#64748b;font-style:italic;">{disclaimer}</p>
                            </div>
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="padding:32px 48px;background-color:#f8fafc;text-align:center;border-top:1px solid #e2e8f0;">
                            <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">{project_name}</p>
                            <p style="margin:0;font-size:12px;color:#94a3b8;">{footer_text}</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

    return {"subject": subject, "html": html, "plain_text": plain_text}
