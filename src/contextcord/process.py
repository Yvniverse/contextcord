"""Bounded capture for locally trusted validation commands (not a sandbox)."""
import os
import signal
import subprocess
import threading


def capture(command, *, cwd, timeout, max_bytes):
    buffers = [bytearray(), bytearray()]
    overflow = [False, False]
    proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, shell=False,
                            start_new_session=os.name != 'nt')

    def drain(stream, index):
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                remaining = max_bytes - len(buffers[index])
                buffers[index].extend(chunk[:max(0, remaining)])
                if len(chunk) > remaining:
                    overflow[index] = True
        finally:
            stream.close()

    threads = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((proc.stdout, proc.stderr))]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=2)
    incomplete = any(t.is_alive() for t in threads)
    # Discard oversized streams entirely: truncation must not leak a partial secret.
    streams = ['[CONTEXTCORD OUTPUT TRUNCATED]\n' if overflow[i] or threads[i].is_alive()
               else bytes(b).decode('utf-8', 'replace') for i, b in enumerate(buffers)]
    return proc.returncode, streams[0], streams[1], timed_out, overflow, incomplete
