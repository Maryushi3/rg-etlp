# ETLP Display Web UI

A simple Flask web interface for controlling an ETLP LED display over RS485.

## Requirements

- Python 3.10+
- `flask` and `pyserial` (install via `pip install -r ../requirements.txt`)

## Usage

```bash
# Auto-detect port and start
./start.sh

# Or specify port manually
./start.sh /dev/tty.usbmodemXXXX
# or:
python3 app.py --port /dev/tty.usbmodemXXXX
```

Optional flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | (required) | Serial port path |
| `--addr` | 16 | Display address |
| `--baud` | 9600 | Baud rate |
| `--host` | `127.0.0.1` | HTTP listen address |
| `--http-port` | 8080 | HTTP port |

Open `http://127.0.0.1:8080` in a browser to access the form.

The app runs in the foreground. Use `&` or a second terminal window to keep it running alongside your shell.

The web UI enforces a **safe unique-text limit of 332 characters total** across lines 1–4. The display's internal compression allows much longer repetitive text, but that is best controlled via the CLI where the content can be crafted deliberately.

## Fields (form order)

| Form field | CLI flag | Display position |
|------------|----------|------------------|
| Line 1 (Train) | `--l1` / `--train` | Row 1 = KierL3 |
| Line 2 (Departure) | `--l2` / `--departure` | Row 2 = KierL4 |
| Line 3 (Route) | `--l3` / `--route` | Row 3 = KierL5 |
| Line 4 (Destination) | `--l4` / `--destination` | Row 4 = KierL6 |
| Wagon number | `--wag` | Lower right corner |

## API endpoints

- `POST /send` — form-encoded fields (`l1`, `l2`, `l3`, `l4`, `wag`)
- `POST /clear` — clears the display
