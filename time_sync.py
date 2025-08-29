# Time synchronization utilities

import sys
import subprocess
import time
from datetime import datetime, timezone
import ntplib
from logging_config import logger

def sync_time_with_ntp():
    """Synchronizes the system's time with an NTP server."""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3, timeout=5)  # response.tx_time is already in system time
        ntp_time = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
        offset = response.offset

        # Log the time synchronization details
        logger.info(".4f")

        # --- Actual System Time Setting ---
        if sys.platform.startswith('linux'):
            # Linux: Use 'date' command. Requires sudo.
            # Format: YYYY-MM-DD HH:MM:SS UTC
            time_str = ntp_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            cmd = ['sudo', 'date', '-s', time_str]
            logger.info(f"Attempting to set system time on Linux: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info(f"System time successfully set on Linux: {result.stdout.strip()}")
            else:
                logger.error(f"Failed to set system time on Linux. Error: {result.stderr.strip()}")
                return False
        elif sys.platform.startswith('win'):
            # Windows: Use 'w32tm' command. Requires admin privileges.
            # First, configure to sync from manual peer, then force resync.
            max_retries = 3
            retry_delay_seconds = 5
            for attempt in range(max_retries):
                try:
                    logger.info(f"Attempting to set system time on Windows using w32tm (Attempt {attempt + 1}/{max_retries}).")
                    # Configure NTP client to use pool.ntp.org and be reliable
                    # w32tm /config /manualpeerlist:time.windows.com,0x1 /syncfromflags:manual /reliable:yes /update
                    # w32tm /config /update /manualpeerlist:"0.pool.ntp.org,0x8 1.pool.ntp.org,0x8 2.pool.ntp.org,0x8 3.pool.ntp.org,0x8" /syncfromflags:MANUAL

                    config_result = subprocess.run(['w32tm', '/config', '/manualpeerlist:\"0.pool.ntp.org,0x8 1.pool.ntp.org,0x8 2.pool.ntp.org,0x8 3.pool.ntp.org,0x8\"', '/syncfromflags:manual', '/reliable:yes', '/update'], capture_output=True, text=True, check=True)
                    logger.info("w32tm /config command issued on Windows.")
                    if config_result.stdout:
                        logger.info(f"w32tm /config stdout: {config_result.stdout.strip()}")
                    if config_result.stderr:
                        logger.warning(f"w32tm /config stderr: {config_result.stderr.strip()}")

                    # Force resync
                    resync_result = subprocess.run(['w32tm', '/resync', '/force'], capture_output=True, text=True, check=True)
                    logger.info("System time resync command issued on Windows.")
                    if resync_result.stdout:
                        logger.info(f"w32tm /resync stdout: {resync_result.stdout.strip()}")
                    if resync_result.stderr:
                        logger.warning(f"w32tm /resync stderr: {resync_result.stderr.strip()}")

                    # Check if resync was successful based on output
                    if "The command completed successfully." in resync_result.stdout:  # or similar success message
                        logger.info("System time resync reported success.")
                        return True
                    else:
                        logger.warning("w32tm /resync did not report success. Retrying...")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay_seconds)
                        else:
                            logger.error(f"Failed to resync system time after {max_retries} attempts.")
                            return False

                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to set system time on Windows: {e.output.strip()}")
                    if e.returncode == 2147942405:  # 0x80070005 - Access is denied
                        logger.error(f"Failed to set system time on Windows: Access Denied. Please run the script as an Administrator. Error: {e.stderr.strip()}")
                        return False  # No point in retrying if it's an access denied error
                    else:
                        logger.error(f"Failed to set system time on Windows. Command: {e.cmd}, Return Code: {e.returncode}, Error: {e.stderr.strip()}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay_seconds)
                        else:
                            logger.error(f"Failed to resync system time after {max_retries} attempts due to CalledProcessError.")
                            return False
                except Exception as e:
                    logger.error(f"An unexpected error occurred during time sync attempt: {e}", exc_info=True)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay_seconds)
                    else:
                        logger.error(f"Failed to resync system time after {max_retries} attempts due to unexpected error.")
                        return False
            return False  # All retries failed
        else:
            logger.warning(f"System time setting not implemented for platform: {sys.platform}")

        return True

    except Exception as e:
        logger.error(f"Time synchronization failed: {e}", exc_info=True)
        return False