from app.schemas.user import Language


def generate_password_reset_email(
    reset_link: str, project_name: str, lang: str = Language.EN
) -> dict[str, str]:
    """
    Generate subject, HTML, and plain text for password reset email.
    """
    if lang == Language.TR:
        subject = "Parola Sıfırlama İsteği"
        greeting = "Merhaba,"
        message = "Hesabınız için şifre sıfırlama talebinde bulundunuz. Şifrenizi yenilemek için aşağıdaki butona tıklayabilirsiniz:"
        btn_text = "Şifremi Yenile"
        disclaimer = "Eğer bu talebi siz yapmadıysanız, bu e-postayı güvenle görmezden gelebilirsiniz.<br>Bu bağlantı kısa bir süreliğine geçerlidir."
        footer_text = f"&copy; {project_name}. Tüm hakları saklıdır."
        plain_text = f"Lütfen bağlantıya tıklayarak parolanızı sıfırlayın: {reset_link}"
    else:
        subject = "Password Reset Request"
        greeting = "Hello,"
        message = "You have requested a password reset for your account. You can click the button below to reset your password:"
        btn_text = "Reset Password"
        disclaimer = "If you didn't request this, you can safely ignore this email.<br>This link is valid for a short time."
        footer_text = f"&copy; {project_name}. All rights reserved."
        plain_text = f"Please reset your password by clicking on the link: {reset_link}"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{subject}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            color: #333333;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 40px auto;
            background-color: #ffffff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }}
        .header {{
            text-align: center;
            padding-bottom: 20px;
            border-bottom: 1px solid #eeeeee;
        }}
        .content {{
            padding: 20px 0;
            line-height: 1.6;
        }}
        .button-wrapper {{
            text-align: center;
            margin: 30px 0;
        }}
        .button {{
            background-color: #007bff;
            color: #ffffff;
            text-decoration: none;
            padding: 12px 24px;
            border-radius: 4px;
            font-weight: bold;
            display: inline-block;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #888888;
            padding-top: 20px;
            border-top: 1px solid #eeeeee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">{project_name}</h2>
        </div>
        <div class="content">
            <p>{greeting}</p>
            <p>{message}</p>
            <div class="button-wrapper">
                <a href="{reset_link}" class="button">{btn_text}</a>
            </div>
            <p>{disclaimer}</p>
        </div>
        <div class="footer">
            <p>{footer_text}</p>
        </div>
    </div>
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
        greeting = "Merhaba,"
        message = "Aramıza hoş geldiniz! Kayıt işleminizi tamamlamak ve e-posta adresinizi doğrulamak için lütfen aşağıdaki butona tıklayın:"
        btn_text = "E-posta Adresimi Doğrula"
        disclaimer = "Eğer bu hesabı siz oluşturmadıysanız, bu e-postayı görmezden gelebilirsiniz."
        footer_text = f"&copy; {project_name}. Tüm hakları saklıdır."
        plain_text = (
            f"Lütfen bağlantıya tıklayarak e-postanızı doğrulayın: {verify_link}"
        )
    else:
        subject = "Verify Your Email"
        greeting = "Hello,"
        message = "Welcome! Please click the button below to complete your registration and verify your email address:"
        btn_text = "Verify My Email"
        disclaimer = "If you didn't create this account, you can ignore this email."
        footer_text = f"&copy; {project_name}. All rights reserved."
        plain_text = f"Please verify your email by clicking on the link: {verify_link}"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{subject}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            color: #333333;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 40px auto;
            background-color: #ffffff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }}
        .header {{
            text-align: center;
            padding-bottom: 20px;
            border-bottom: 1px solid #eeeeee;
        }}
        .content {{
            padding: 20px 0;
            line-height: 1.6;
        }}
        .button-wrapper {{
            text-align: center;
            margin: 30px 0;
        }}
        .button {{
            background-color: #28a745;
            color: #ffffff;
            text-decoration: none;
            padding: 12px 24px;
            border-radius: 4px;
            font-weight: bold;
            display: inline-block;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #888888;
            padding-top: 20px;
            border-top: 1px solid #eeeeee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">{project_name}</h2>
        </div>
        <div class="content">
            <p>{greeting}</p>
            <p>{message}</p>
            <div class="button-wrapper">
                <a href="{verify_link}" class="button">{btn_text}</a>
            </div>
            <p>{disclaimer}</p>
        </div>
        <div class="footer">
            <p>{footer_text}</p>
        </div>
    </div>
</body>
</html>"""

    return {"subject": subject, "html": html, "plain_text": plain_text}
