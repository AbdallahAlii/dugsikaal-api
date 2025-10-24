# app/common/error_handling.py

from pydantic import ValidationError


def format_validation_error(e: ValidationError) -> str:
    """Convert Pydantic ValidationError to user-friendly messages"""
    error_messages = []
    for error in e.errors():
        field = error['loc'][0] if error['loc'] else 'field'
        msg = error['msg']

        # Clean up Pydantic's technical error messages
        if "Value error" in msg:
            if "Value error, " in msg:
                clean_msg = msg.split("Value error, ")[1]
            else:
                clean_msg = msg.replace("Value error", "").strip()
            error_messages.append(f"{clean_msg}")
        else:
            error_messages.append(f"{field}: {msg}")

    return ". ".join(error_messages)