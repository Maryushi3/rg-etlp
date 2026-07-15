#!/usr/bin/env python3
"""Basic tests for the ETLP protocol implementation and web UI."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import etlp_send


class AddressEncodingTests(unittest.TestCase):
    def test_encode_address_known_values(self):
        self.assertEqual(etlp_send.encode_address(0), "03")
        self.assertEqual(etlp_send.encode_address(16), "43")
        self.assertEqual(etlp_send.encode_address(17), "47")
        self.assertEqual(etlp_send.encode_address(31), "7F")
        self.assertEqual(etlp_send.encode_address(40), "A3")


class CommandFrameTests(unittest.TestCase):
    def test_crc_hex_command(self):
        # Documented example: 43020A -> checksum 3A
        self.assertEqual(etlp_send.crc_hex_command("43020A"), "3A")

    def test_cmd_clear_buffer_addr_16(self):
        frame = etlp_send.cmd_clear_buffer(16)
        # Should be STX + "43020A3A" + ETX
        self.assertEqual(frame[0], 0x02)
        self.assertEqual(frame[-1], 0x03)
        self.assertEqual(frame[1:-1].decode("ascii"), "43020A3A")

    def test_cmd_send_buffer_addr_17(self):
        frame = etlp_send.cmd_send_buffer(17)
        self.assertEqual(frame[1:-1].decode("ascii"), "47020835")


class DataPacketTests(unittest.TestCase):
    def test_data_packet_format(self):
        pkt = etlp_send.make_data_packet(
            addr=16,
            nr_wagonu="001",
            nr_poc="123",
            stacja_pocz="WARSZAWA",
            przebieg="R-7",
            stacja_docel="KRAKOW",
        )
        self.assertEqual(pkt[0], 0x02)
        self.assertEqual(pkt[-1], 0x03)

        payload = pkt[1:-1]
        body = payload[:-2]
        crc_text = payload[-2:].decode("ascii")
        crc_computed = f"{etlp_send.crc_bytes(body):02X}"
        self.assertEqual(crc_text, crc_computed)

    def test_data_packet_too_large_raises(self):
        long_text = "A" * 1000
        with self.assertRaises(ValueError):
            etlp_send.make_data_packet(
                addr=16,
                nr_wagonu="",
                nr_poc=long_text,
                stacja_pocz="",
                przebieg="",
                stacja_docel="",
            )

    def test_data_packet_max_size_allowed(self):
        # Exactly 998 body bytes should succeed with NrWag.
        overhead = "43FF3BNrWag\r   \rKierL3\r\rKierL4\r\rKierL5\r\rKierL6\r\r"
        long_text = "A" * (998 - len(overhead))
        pkt = etlp_send.make_data_packet(
            addr=16,
            nr_wagonu="   ",
            nr_poc=long_text,
            stacja_pocz="",
            przebieg="",
            stacja_docel="",
        )
        self.assertEqual(len(pkt), 1002)

    def test_data_packet_without_nrwag(self):
        # Omitting NrWag must produce a valid packet without the NrWag key.
        pkt = etlp_send.make_data_packet(
            addr=16,
            nr_wagonu="",
            nr_poc="123",
            stacja_pocz="WARSZAWA",
            przebieg="R-7",
            stacja_docel="KRAKOW",
        )
        body = pkt[1:-3]  # STX + body + CRC(-2) + ETX
        text = body.decode("cp852")
        self.assertNotIn("NrWag", text, "NrWag key must be omitted when value is empty")
        self.assertIn("KierL3", text)
        self.assertIn("123", text)
        self.assertEqual(pkt[0], 0x02)
        self.assertEqual(pkt[-1], 0x03)
        # CRC must still be valid
        payload = pkt[1:-1]
        crc_stored = payload[-2:].decode("ascii")
        crc_computed = f"{etlp_send.crc_bytes(payload[:-2]):02X}"
        self.assertEqual(crc_stored, crc_computed)


class SanitizationTests(unittest.TestCase):
    def test_sanitize_text_allows_normal_text(self):
        self.assertEqual(etlp_send.sanitize_text("WARSZAWA 123"), "WARSZAWA 123")

    def test_sanitize_text_allows_oem_glyphs(self):
        # 0x01-0x1F are displayable OEM glyphs, only STX/ETX/CR are banned
        self.assertEqual(etlp_send.sanitize_text("hello\x01world"), "hello\x01world")
        self.assertEqual(etlp_send.sanitize_text("\x07\x0E\x0F"), "\x07\x0E\x0F")
        self.assertEqual(etlp_send.sanitize_text("line\nbreak"), "line\nbreak")

    def test_sanitize_text_rejects_framing_bytes(self):
        with self.assertRaises(ValueError):
            etlp_send.sanitize_text("\x02")  # STX
        with self.assertRaises(ValueError):
            etlp_send.sanitize_text("\x03")  # ETX
        with self.assertRaises(ValueError):
            etlp_send.sanitize_text("\x0D")  # CR


class WebUiImportTests(unittest.TestCase):
    def test_app_importable_without_args(self):
        """Importing web-ui/app.py must not call sys.exit() for argparse."""
        # Remove any cached import first.
        if "app" in sys.modules:
            del sys.modules["app"]
        web_ui_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web-ui")
        sys.path.insert(0, web_ui_dir)
        try:
            import app
            self.assertIsNotNone(app.app)
            self.assertEqual(app.ADDR, 16)
            self.assertEqual(app.BAUD, 9600)
            self.assertIsNone(app.SERIAL_PORT)
        finally:
            sys.path.remove(web_ui_dir)


if __name__ == "__main__":
    unittest.main()
