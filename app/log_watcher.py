import os
import asyncio
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app.config import LOG_PATH
from app.log_parser import parse_log_line
from app.database import SessionLocal, AccessLog, IntruderEvent
from app.intruder_detection import analyze_log
from app.telegram_alerter import send_alert_sync


class LogFileHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        self.file_position = 0
        self._init_position()

    def _init_position(self):
        """Start reading from end of file."""
        if os.path.exists(LOG_PATH):
            self.file_position = os.path.getsize(LOG_PATH)

    def on_modified(self, event):
        if event.src_path == LOG_PATH:
            self._read_new_lines()

    def _read_new_lines(self):
        """Read new lines from the log file."""
        try:
            with open(LOG_PATH, "r") as f:
                f.seek(self.file_position)
                new_lines = f.readlines()
                self.file_position = f.tell()

                for line in new_lines:
                    if line.strip():
                        self.callback(line)
        except Exception as e:
            print(f"Error reading log file: {e}")


class LogWatcher:
    def __init__(self):
        self.observer = None
        self.running = False
        self.new_log_callbacks = []
        self._auto_block_queue = []

    def add_callback(self, callback):
        """Add a callback for new log entries."""
        self.new_log_callbacks.append(callback)

    def _schedule_auto_block(self, event: dict):
        """Schedule auto-block check for an intruder event."""
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Import here to avoid circular imports
            from app.auto_blocker import process_intruder_event

            # Create task for async processing
            if loop.is_running():
                asyncio.create_task(process_intruder_event(event))
            else:
                loop.run_until_complete(process_intruder_event(event))
        except Exception as e:
            print(f"Auto-block error: {e}")

    def process_line(self, line: str):
        """Process a single log line."""
        parsed = parse_log_line(line)
        if not parsed:
            return

        # HONEYPOT CHECK FIRST - instant block before anything else
        try:
            from app.auto_blocker import check_and_block_honeypot
            honeypot_result = check_and_block_honeypot(
                ip=parsed.ip,
                path=parsed.path,
                host=parsed.host
            )
            if honeypot_result and honeypot_result.get("success"):
                print(f"🍯 Honeypot block: {parsed.ip} -> {parsed.path[:50]}")
        except Exception as e:
            print(f"Honeypot check error: {e}")

        # Store in database
        db = SessionLocal()
        try:
            log_entry = AccessLog(
                timestamp=parsed.timestamp,
                ip=parsed.ip,
                user=parsed.user,
                method=parsed.method,
                path=parsed.path,
                protocol=parsed.protocol,
                status=parsed.status,
                bytes=parsed.bytes,
                referer=parsed.referer,
                user_agent=parsed.user_agent,
                request_num=parsed.request_num,
                router=parsed.router,
                backend=parsed.backend,
                duration_ms=parsed.duration_ms,
                host=parsed.host,
            )
            db.add(log_entry)
            db.commit()

            # Check for intrusions
            events = analyze_log(parsed)
            for event in events:
                intruder = IntruderEvent(
                    timestamp=event.get("timestamp", datetime.utcnow()),
                    ip=event["ip"],
                    reason=event["reason"],
                    details=event.get("details"),
                    request_count=event.get("request_count"),
                    status_code=event.get("status_code"),
                    host=event.get("host"),
                )
                db.add(intruder)
                db.commit()

                # Send Telegram alert (without Ollama - on-demand now)
                send_alert_sync(event)

                # Try auto-blocking in background (async)
                try:
                    self._schedule_auto_block(event)
                except Exception as e:
                    print(f"Auto-block scheduling failed: {e}")

            # Notify callbacks
            for callback in self.new_log_callbacks:
                try:
                    callback(parsed)
                except Exception as e:
                    print(f"Callback error: {e}")

        except Exception as e:
            print(f"Database error: {e}")
            db.rollback()
        finally:
            db.close()

    def start(self):
        """Start watching the log file."""
        if self.running:
            return

        log_dir = str(Path(LOG_PATH).parent)
        if not os.path.exists(log_dir):
            print(f"Log directory does not exist: {log_dir}")
            return

        handler = LogFileHandler(self.process_line)
        self.observer = Observer()
        self.observer.schedule(handler, log_dir, recursive=False)
        self.observer.start()
        self.running = True
        print(f"Started watching: {LOG_PATH}")

    def stop(self):
        """Stop watching the log file."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.running = False
            print("Stopped log watcher")


# Global watcher instance
watcher = LogWatcher()
