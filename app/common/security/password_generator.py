import random
import string


def generate_random_password(length: int = 8) -> str:
    """
    Generates a random password of a specified length, consisting only of digits (numbers).

    Args:
        length: The desired length of the password. Defaults to 8.

    Returns:
        A randomly generated password string composed only of digits.
    """
    # Define the characters to use for the password: only digits
    characters = string.digits

    # Generate the password by randomly choosing from the digits
    password = ''.join(random.choices(characters, k=length))
    return password