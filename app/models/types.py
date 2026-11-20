"""Custom SQLAlchemy column types."""

from sqlalchemy import Text, TypeDecorator

from app.secret_cipher import decrypt_secret, encrypt_secret


class EncryptedText(TypeDecorator):
    """Text that is Fernet-encrypted at rest.

    Application code — the API, the executor, version snapshots — works in
    plaintext and never sees the cipher: encryption happens in the bind
    processor on the way into the database, decryption in the result
    processor on the way out. Values stored before this type existed carry
    no marker and pass through unchanged until the startup sweep rewrites
    them.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_secret(value)
