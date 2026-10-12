import contextvars
import logging

from pythonjsonlogger.json import JsonFormatter

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
tenant_id: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="-")
product_id: contextvars.ContextVar[str] = contextvars.ContextVar("product_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        record.tenant_id = tenant_id.get()
        record.product_id = product_id.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(request_id)s %(tenant_id)s %(product_id)s"
        )
    )
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
