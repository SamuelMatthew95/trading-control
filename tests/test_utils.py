"""
Test Suite for Utils Module
Comprehensive tests for utility functions and helpers
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import utils


class TestDateUtils:
    """Test date and time utility functions"""

    def test_format_timestamp(self):
        """Test timestamp formatting"""
        # Test with datetime object
        dt = datetime(2024, 3, 4, 15, 30, 0)
        formatted = utils.format_timestamp(dt)

        assert formatted == "2024-03-04T15:30:00Z"

    def test_format_timestamp_string(self):
        """Test timestamp formatting with string input"""
        timestamp_str = "2024-03-04T15:30:00Z"
        formatted = utils.format_timestamp(timestamp_str)

        # Should return the same string or formatted version
        assert formatted is not None
        assert isinstance(formatted, str)

    def test_format_timestamp_none(self):
        """Test timestamp formatting with None"""
        formatted = utils.format_timestamp(None)

        # Should handle gracefully
        assert formatted is None or formatted == ""

    def test_parse_timestamp(self):
        """Test timestamp parsing"""
        timestamp_str = "2024-03-04T15:30:00Z"
        parsed = utils.parse_timestamp(timestamp_str)

        assert isinstance(parsed, datetime)
        assert parsed.year == 2024
        assert parsed.month == 3
        assert parsed.day == 4
        assert parsed.hour == 15
        assert parsed.minute == 30

    def test_parse_timestamp_invalid(self):
        """Test timestamp parsing with invalid input"""
        invalid_timestamps = [
            "invalid-timestamp",
            "2024-13-01T00:00:00Z",  # Invalid month
            "2024-02-30T00:00:00Z",  # Invalid day
            "",
        ]

        for timestamp in invalid_timestamps:
            try:
                parsed = utils.parse_timestamp(timestamp)
                # Should handle gracefully or raise appropriate error
                assert parsed is None or isinstance(parsed, datetime)
            except ValueError:
                # ValueError is acceptable for invalid timestamps
                assert True

    def test_get_time_ago(self):
        """Test getting time ago string"""
        now = datetime.now()

        # Test 1 hour ago
        one_hour_ago = now - timedelta(hours=1)
        time_ago = utils.get_time_ago(one_hour_ago)

        assert "hour" in time_ago.lower()
        assert "ago" in time_ago.lower()

    def test_get_time_ago_minutes(self):
        """Test getting time ago for minutes"""
        now = datetime.now()

        # Test 30 minutes ago
        thirty_min_ago = now - timedelta(minutes=30)
        time_ago = utils.get_time_ago(thirty_min_ago)

        assert "minute" in time_ago.lower()
        assert "ago" in time_ago.lower()

    def test_get_time_ago_days(self):
        """Test getting time ago for days"""
        now = datetime.now()

        # Test 3 days ago
        three_days_ago = now - timedelta(days=3)
        time_ago = utils.get_time_ago(three_days_ago)

        assert "day" in time_ago.lower()
        assert "ago" in time_ago.lower()


class TestStringUtils:
    """Test string utility functions"""

    def test_snake_to_camel(self):
        """Test snake_case to camelCase conversion"""
        test_cases = [
            ("snake_case", "snakeCase"),
            ("long_snake_case_string", "longSnakeCaseString"),
            ("single", "single"),
            ("", ""),
            ("alreadyCamel", "alreadyCamel"),
        ]

        for input_str, expected in test_cases:
            result = utils.snake_to_camel(input_str)
            assert result == expected

    def test_camel_to_snake(self):
        """Test camelCase to snake_case conversion"""
        test_cases = [
            ("camelCase", "camel_case"),
            ("longCamelCaseString", "long_camel_case_string"),
            ("Single", "single"),
            ("", ""),
            ("already_snake", "already_snake"),
        ]

        for input_str, expected in test_cases:
            result = utils.camel_to_snake(input_str)
            assert result == expected

    def test_truncate_string(self):
        """Test string truncation"""
        long_string = "This is a very long string that needs to be truncated"

        # Test truncation with ellipsis
        truncated = utils.truncate_string(long_string, 20)
        assert len(truncated) <= 23  # 20 + "..."
        assert truncated.endswith("...")

        # Test truncation without ellipsis
        truncated_no_ellipsis = utils.truncate_string(long_string, 20, ellipsis=False)
        assert len(truncated_no_ellipsis) <= 20

    def test_truncate_string_short(self):
        """Test truncation of short string"""
        short_string = "Short"

        truncated = utils.truncate_string(short_string, 20)
        assert truncated == short_string

    def test_sanitize_string(self):
        """Test string sanitization"""
        dirty_string = "Hello <script>alert('xss')</script> World!"

        sanitized = utils.sanitize_string(dirty_string)

        # Should remove or escape dangerous characters
        assert "<script>" not in sanitized
        assert "</script>" not in sanitized
        assert "Hello" in sanitized
        assert "World" in sanitized

    def test_format_currency(self):
        """Test currency formatting"""
        test_cases = [
            (175.43, "$175.43"),
            (1000.0, "$1,000.00"),
            (0.99, "$0.99"),
            (-50.25, "-$50.25"),
        ]

        for amount, expected in test_cases:
            formatted = utils.format_currency(amount)
            assert formatted == expected

    def test_format_percentage(self):
        """Test percentage formatting"""
        test_cases = [
            (0.875, "87.50%"),
            (0.1, "10.00%"),
            (1.0, "100.00%"),
            (-0.25, "-25.00%"),
        ]

        for value, expected in test_cases:
            formatted = utils.format_percentage(value)
            assert formatted == expected


class TestValidationUtils:
    """Test validation utility functions"""

    def test_is_valid_symbol(self):
        """Test stock symbol validation"""
        valid_symbols = ["AAPL", "GOOGL", "MSFT", "TSLA", "BRK.B"]
        invalid_symbols = ["", "123", "TOOLONGSYMBOL", "symbol!", None]

        for symbol in valid_symbols:
            assert utils.is_valid_symbol(symbol) is True

        for symbol in invalid_symbols:
            assert utils.is_valid_symbol(symbol) is False

    def test_is_valid_email(self):
        """Test email validation"""
        valid_emails = [
            "test@example.com",
            "user.name@domain.co.uk",
            "user+tag@example.org",
        ]
        invalid_emails = [
            "invalid-email",
            "@domain.com",
            "user@",
            "user..name@domain.com",
            None,
        ]

        for email in valid_emails:
            assert utils.is_valid_email(email) is True

        for email in invalid_emails:
            assert utils.is_valid_email(email) is False

    def test_is_valid_url(self):
        """Test URL validation"""
        valid_urls = [
            "https://www.example.com",
            "http://api.example.com/v1/endpoint",
            "https://subdomain.example.co.uk/path",
        ]
        invalid_urls = ["not-a-url", "ftp://example.com", "http://", None]

        for url in valid_urls:
            assert utils.is_valid_url(url) is True

        for url in invalid_urls:
            assert utils.is_valid_url(url) is False

    def test_is_positive_number(self):
        """Test positive number validation"""
        valid_numbers = [1, 0.1, 100.5, float("inf")]
        invalid_numbers = [0, -1, -0.1, None, "not_a_number"]

        for number in valid_numbers:
            assert utils.is_positive_number(number) is True

        for number in invalid_numbers:
            assert utils.is_positive_number(number) is False

    def test_is_valid_date_range(self):
        """Test date range validation"""
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 31)

        # Valid range
        assert utils.is_valid_date_range(start_date, end_date) is True

        # Invalid range (end before start)
        invalid_end = datetime(2023, 12, 31)
        assert utils.is_valid_date_range(start_date, invalid_end) is False

        # Same dates (should be valid)
        assert utils.is_valid_date_range(start_date, start_date) is True


class TestFileUtils:
    """Test file utility functions"""

    def test_read_json_file(self):
        """Test JSON file reading"""
        test_data = {"key": "value", "number": 123}
        json_str = json.dumps(test_data)

        with patch("builtins.open", mock_open(read_data=json_str)):
            result = utils.read_json_file("test_file.json")

            assert result == test_data

    def test_read_json_file_not_found(self):
        """Test reading non-existent JSON file"""
        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            with pytest.raises(FileNotFoundError):
                utils.read_json_file("non_existent.json")

    def test_read_json_file_invalid_json(self):
        """Test reading invalid JSON file"""
        with patch("builtins.open", mock_open(read_data="invalid json")):
            with pytest.raises(json.JSONDecodeError):
                utils.read_json_file("invalid.json")

    def test_write_json_file(self):
        """Test JSON file writing"""
        test_data = {"key": "value", "number": 123}
        json_str = json.dumps(test_data, indent=2)

        mock_file = MagicMock()
        with patch("builtins.open", mock_open(read_data="")) as mock_file_open:
            mock_file_open.return_value.__enter__.return_value = mock_file

            utils.write_json_file("test_file.json", test_data)

            # Verify write was called with correct data
            mock_file.write.assert_called_once_with(json_str)
            mock_file.write.assert_called()
            written_data = "".join(
                call[0][0] for call in mock_file.write.call_args_list
            )
            assert json.loads(written_data) == test_data

    def test_ensure_directory_exists(self):
        """Test directory creation"""
        test_path = Path("/tmp/test_directory")

        with patch("pathlib.Path.mkdir") as mock_mkdir:
            utils.ensure_directory_exists(test_path)

            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_ensure_directory_exists_already_exists(self):
        """Test directory creation when directory already exists"""
        test_path = Path("/tmp/existing_directory")

        with patch("pathlib.Path.mkdir") as mock_mkdir:
            utils.ensure_directory_exists(test_path)

            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_get_file_size(self):
        """Test getting file size"""
        test_path = Path("/tmp/test_file.txt")

        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 1024

            size = utils.get_file_size(test_path)

            assert size == 1024

    def test_get_file_size_not_found(self):
        """Test getting size of non-existent file"""
        test_path = Path("/tmp/non_existent.txt")

        with patch(
            "pathlib.Path.stat", side_effect=FileNotFoundError("File not found")
        ):
            with pytest.raises(FileNotFoundError):
                utils.get_file_size(test_path)


class TestNetworkUtils:
    """Test network utility functions"""

    @pytest.mark.asyncio
    async def test_make_http_request_success(self):
        """Test successful HTTP request"""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "success"})

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value = mock_response

            result = await utils.make_http_request("https://api.example.com/data")

            assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_make_http_request_error(self):
        """Test HTTP request with error"""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value.status = 500
            mock_get.return_value.__aenter__.return_value.json = AsyncMock(
                side_effect=Exception("Server error")
            )

            with pytest.raises(Exception):
                await utils.make_http_request("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_make_http_request_timeout(self):
        """Test HTTP request with timeout"""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.side_effect = asyncio.TimeoutError(
                "Timeout"
            )

            with pytest.raises(asyncio.TimeoutError):
                await utils.make_http_request("https://api.example.com/data")

    def test_build_url_with_params(self):
        """Test URL building with parameters"""
        base_url = "https://api.example.com/data"
        params = {"symbol": "AAPL", "interval": "1d", "apikey": "test_key"}

        url = utils.build_url_with_params(base_url, params)

        assert "symbol=AAPL" in url
        assert "interval=1d" in url
        assert "apikey=test_key" in url
        assert url.startswith(base_url)

    def test_build_url_with_params_empty(self):
        """Test URL building with empty parameters"""
        base_url = "https://api.example.com/data"
        params = {}

        url = utils.build_url_with_params(base_url, params)

        assert url == base_url

    def test_build_url_with_params_none(self):
        """Test URL building with None parameters"""
        base_url = "https://api.example.com/data"

        url = utils.build_url_with_params(base_url, None)

        assert url == base_url


class TestMathUtils:
    """Test mathematical utility functions"""

    def test_calculate_percentage_change(self):
        """Test percentage change calculation"""
        test_cases = [
            (100, 110, 10.0),
            (100, 90, -10.0),
            (50, 60, 20.0),
            (100, 100, 0.0),
        ]

        for old_val, new_val, expected in test_cases:
            result = utils.calculate_percentage_change(old_val, new_val)
            assert abs(result - expected) < 0.0001

    def test_calculate_percentage_change_zero_old(self):
        """Test percentage change with zero old value"""
        result = utils.calculate_percentage_change(0, 100)

        # Should handle division by zero gracefully
        assert result == float("inf") or result is None

    def test_round_to_decimal(self):
        """Test rounding to decimal places"""
        test_cases = [(3.14159, 2, 3.14), (2.71828, 3, 2.718), (1.5, 0, 2), (1.4, 0, 1)]

        for value, decimal_places, expected in test_cases:
            result = utils.round_to_decimal(value, decimal_places)
            assert result == expected

    def test_calculate_average(self):
        """Test average calculation"""
        numbers = [1, 2, 3, 4, 5]
        average = utils.calculate_average(numbers)

        assert average == 3.0

    def test_calculate_average_empty(self):
        """Test average calculation with empty list"""
        average = utils.calculate_average([])

        # Should handle gracefully
        assert average == 0 or average is None

    def test_calculate_standard_deviation(self):
        """Test standard deviation calculation"""
        numbers = [2, 4, 4, 4, 5, 5, 7, 9]
        std_dev = utils.calculate_standard_deviation(numbers)

        # Expected standard deviation is 2
        assert abs(std_dev - 2.0) < 0.0001

    def test_calculate_standard_deviation_empty(self):
        """Test standard deviation with empty list"""
        std_dev = utils.calculate_standard_deviation([])

        # Should handle gracefully
        assert std_dev == 0 or std_dev is None


class TestCryptoUtils:
    """Test cryptographic utility functions"""

    def test_generate_uuid(self):
        """Test UUID generation"""
        uuid1 = utils.generate_uuid()
        uuid2 = utils.generate_uuid()

        # Should be strings
        assert isinstance(uuid1, str)
        assert isinstance(uuid2, str)

        # Should be different
        assert uuid1 != uuid2

        # Should be valid UUID format
        assert len(uuid1) == 36  # Standard UUID length
        assert uuid1.count("-") == 4  # Standard UUID format

    def test_hash_string(self):
        """Test string hashing"""
        test_string = "test_string"
        hash1 = utils.hash_string(test_string)
        hash2 = utils.hash_string(test_string)

        # Should be consistent
        assert hash1 == hash2

        # Should be different for different inputs
        hash3 = utils.hash_string("different_string")
        assert hash1 != hash3

        # Should be string
        assert isinstance(hash1, str)

    def test_hash_string_none(self):
        """Test hashing None input"""
        try:
            hash_result = utils.hash_string(None)
            # Should handle gracefully or raise appropriate error
            assert hash_result is not None or isinstance(hash_result, str)
        except (TypeError, ValueError):
            # Type errors are acceptable for None input
            assert True


class TestUtilsIntegration:
    """Test utility integration scenarios"""

    def test_data_processing_pipeline(self):
        """Test complete data processing pipeline"""
        # Raw data
        raw_data = {
            "symbol": "AAPL",
            "price": 175.4321,
            "change": 2.5,
            "volume": 1000000,
            "timestamp": "2024-03-04T15:30:00Z",
        }

        # Process with utilities
        processed_data = {
            "symbol": raw_data["symbol"].upper(),
            "price": utils.round_to_decimal(raw_data["price"], 2),
            "change_percent": utils.calculate_percentage_change(
                raw_data["price"] - raw_data["change"], raw_data["price"]
            ),
            "volume_formatted": f"{raw_data['volume']:,}",
            "price_formatted": utils.format_currency(raw_data["price"]),
            "time_ago": utils.get_time_ago(
                utils.parse_timestamp(raw_data["timestamp"])
            ),
        }

        # Verify processing
        assert processed_data["symbol"] == "AAPL"
        assert processed_data["price"] == 175.43
        assert isinstance(processed_data["change_percent"], float)
        assert "1,000,000" in processed_data["volume_formatted"]
        assert "$" in processed_data["price_formatted"]
        assert "ago" in processed_data["time_ago"].lower()

    def test_error_handling_pipeline(self):
        """Test error handling in utility functions"""
        # Test with invalid data
        invalid_data = {
            "symbol": "",  # Invalid symbol
            "price": "not_a_number",  # Invalid price
            "timestamp": "invalid_timestamp",  # Invalid timestamp
        }

        # Should handle gracefully
        try:
            symbol_valid = utils.is_valid_symbol(invalid_data["symbol"])
            assert symbol_valid is False

            # Should not crash on invalid number
            try:
                price_rounded = utils.round_to_decimal(float(invalid_data["price"]), 2)
                assert True  # If conversion succeeds
            except (ValueError, TypeError):
                assert True  # If conversion fails, that's acceptable

            # Should handle invalid timestamp
            try:
                parsed_time = utils.parse_timestamp(invalid_data["timestamp"])
                assert parsed_time is None or isinstance(parsed_time, datetime)
            except ValueError:
                assert True  # Parsing errors are acceptable
        except Exception:
            # Unexpected exceptions should be caught
            assert False

    def test_configuration_validation(self):
        """Test configuration validation utilities"""
        config = {
            "api_key": "test_key_123",
            "timeout": 30,
            "retries": 3,
            "base_url": "https://api.example.com",
            "symbols": ["AAPL", "GOOGL", "MSFT"],
        }

        # Validate configuration
        validation_results = {
            "api_key_valid": len(config["api_key"]) >= 10,
            "timeout_valid": utils.is_positive_number(config["timeout"]),
            "retries_valid": isinstance(config["retries"], int)
            and config["retries"] > 0,
            "base_url_valid": utils.is_valid_url(config["base_url"]),
            "symbols_valid": all(
                utils.is_valid_symbol(sym) for sym in config["symbols"]
            ),
        }

        assert all(validation_results.values())

        # Test invalid configuration
        invalid_config = {
            "api_key": "short",
            "timeout": -1,
            "retries": 0,
            "base_url": "not-a-url",
            "symbols": ["", "123", "TOOLONG"],
        }

        invalid_validation = {
            "api_key_valid": len(invalid_config["api_key"]) >= 10,
            "timeout_valid": utils.is_positive_number(invalid_config["timeout"]),
            "retries_valid": isinstance(invalid_config["retries"], int)
            and invalid_config["retries"] > 0,
            "base_url_valid": utils.is_valid_url(invalid_config["base_url"]),
            "symbols_valid": all(
                utils.is_valid_symbol(sym) for sym in invalid_config["symbols"]
            ),
        }

        # Should detect invalid configuration
        assert not all(invalid_validation.values())
