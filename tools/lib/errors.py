"""
Life Index - Structured Error Codes Module
==========================================
Provides structured error codes for Agent to take different strategies.

Error Code Format: E{module}{type}
- Module: 00=general, 01=file, 02=write, 03=search, 04=weather, 05=edit, 06=index
- Type: 00-99 specific error types

Usage:
    from lib.errors import ErrorCode, LifeIndexError, raise_error

    # Raise structured error
    raise LifeIndexError(ErrorCode.FILE_NOT_FOUND, "Journal file not found", {"path": "/path/to/file"})

    # Or return JSON format
    return LifeIndexError(ErrorCode.WEATHER_API_FAILED, "Weather API timeout").to_json()
"""

from typing import Dict, Any, Optional


class ErrorCode:
    """
    Error code definitions for Life Index.

    Format: E{module(2)}{type(2)}

    Modules:
        00 - General errors
        01 - File operations
        02 - Journal write operations
        03 - Search operations
        04 - Weather API
        05 - Journal edit operations
        06 - Index operations
    """

    # ========== General Errors (00xx) ==========
    UNKNOWN_ERROR = "E0000"
    INVALID_INPUT = "E0001"
    PERMISSION_DENIED = "E0002"
    CONFIG_ERROR = "E0003"
    LOCK_TIMEOUT = "E0005"
    LOCK_ACQUISITION_FAILED = "E0006"

    # ========== File Module (01xx) ==========
    FILE_NOT_FOUND = "E0100"
    FILE_ALREADY_EXISTS = "E0101"
    FILE_CORRUPTED = "E0102"
    PATH_INVALID = "E0103"
    PATH_TRAVERSAL_DETECTED = "E0104"
    DIRECTORY_NOT_FOUND = "E0105"

    # ========== Write Module (02xx) ==========
    WRITE_FAILED = "E0200"
    SEQUENCE_ERROR = "E0201"
    FRONTMATTER_INVALID = "E0202"
    CONTENT_EMPTY = "E0203"
    DATE_INVALID = "E0204"
    ATTACHMENT_COPY_FAILED = "E0205"

    # ========== Search Module (03xx) ==========
    INDEX_NOT_FOUND = "E0300"
    SEARCH_FAILED = "E0301"
    QUERY_EMPTY = "E0302"
    NO_RESULTS = "E0303"

    # ========== Weather Module (04xx) ==========
    WEATHER_API_FAILED = "E0400"
    WEATHER_TIMEOUT = "E0401"
    LOCATION_NOT_FOUND = "E0402"
    WEATHER_PARSE_ERROR = "E0403"

    # ========== Edit Module (05xx) ==========
    JOURNAL_NOT_FOUND = "E0500"
    EDIT_CONFLICT = "E0501"
    FIELD_NOT_RECOGNIZED = "E0502"
    NO_CHANGES_SPECIFIED = "E0503"

    # ========== Index Module (06xx) ==========
    INDEX_BUILD_FAILED = "E0600"
    INDEX_CORRUPTED = "E0601"
    VECTOR_STORE_ERROR = "E0602"
    FTS_INDEX_ERROR = "E0603"


class LifeIndexError(Exception):
    """
    Structured exception for Life Index.

    Attributes:
        code: Error code from ErrorCode class
        message: Human-readable error message
        details: Additional context about the error
        suggestion: Optional suggestion for Agent/User

    Example:
        >>> error = LifeIndexError(
        ...     ErrorCode.WEATHER_API_FAILED,
        ...     "Weather API request failed",
        ...     {"location": "Lagos, Nigeria", "reason": "timeout"},
        ...     "Please manually input weather, or retry later"
        ... )
        >>> error.to_json()
        {
            "success": false,
            "error": {
                "code": "E0400",
                "message": "Weather API request failed",
                "details": {"location": "Lagos, Nigeria", "reason": "timeout"},
                "suggestion": "Please manually input weather, or retry later"
            }
        }
    """

    # Error recovery strategies for Agent
    RECOVERY_STRATEGIES = {
        # Weather errors: Skip weather, continue
        ErrorCode.WEATHER_API_FAILED: "skip_optional",
        ErrorCode.WEATHER_TIMEOUT: "skip_optional",
        ErrorCode.LOCATION_NOT_FOUND: "ask_user",
        ErrorCode.WEATHER_PARSE_ERROR: "skip_optional",
        # File errors: Ask user or fail
        ErrorCode.FILE_NOT_FOUND: "ask_user",
        ErrorCode.PATH_INVALID: "fail",
        ErrorCode.PATH_TRAVERSAL_DETECTED: "fail",
        # Input errors: Ask user
        ErrorCode.INVALID_INPUT: "ask_user",
        ErrorCode.CONTENT_EMPTY: "ask_user",
        ErrorCode.DATE_INVALID: "ask_user",
        # Edit errors: Ask user
        ErrorCode.JOURNAL_NOT_FOUND: "ask_user",
        ErrorCode.NO_CHANGES_SPECIFIED: "ask_user",
        # Search errors: Return empty
        ErrorCode.NO_RESULTS: "continue_empty",
        ErrorCode.QUERY_EMPTY: "ask_user",
        # Lock errors: Retry or ask user
        ErrorCode.LOCK_TIMEOUT: "retry",
        ErrorCode.LOCK_ACQUISITION_FAILED: "retry",
    }

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        suggestion: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.suggestion = suggestion
        super().__init__(message)

    @property
    def recovery_strategy(self) -> str:
        """Get the recommended recovery strategy for this error."""
        return self.RECOVERY_STRATEGIES.get(self.code, "ask_user")

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON format for Agent parsing."""
        error_obj: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "recovery_strategy": self.recovery_strategy,
        }
        if self.suggestion:
            error_obj["suggestion"] = self.suggestion
        result: Dict[str, Any] = {
            "success": False,
            "error": error_obj,
        }
        return result

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# ========== Error Code Descriptions ==========
ERROR_DESCRIPTIONS = {
    # General
    ErrorCode.UNKNOWN_ERROR: "An unknown error occurred",
    ErrorCode.INVALID_INPUT: "Invalid input provided",
    ErrorCode.PERMISSION_DENIED: "Permission denied for operation",
    ErrorCode.CONFIG_ERROR: "Configuration error",
    ErrorCode.LOCK_TIMEOUT: "File lock acquisition timed out",
    ErrorCode.LOCK_ACQUISITION_FAILED: "Failed to acquire file lock",
    # File
    ErrorCode.FILE_NOT_FOUND: "File not found",
    ErrorCode.FILE_ALREADY_EXISTS: "File already exists",
    ErrorCode.FILE_CORRUPTED: "File is corrupted",
    ErrorCode.PATH_INVALID: "Invalid file path",
    ErrorCode.PATH_TRAVERSAL_DETECTED: "Path traversal attempt detected",
    ErrorCode.DIRECTORY_NOT_FOUND: "Directory not found",
    # Write
    ErrorCode.WRITE_FAILED: "Failed to write journal",
    ErrorCode.SEQUENCE_ERROR: "Failed to determine sequence number",
    ErrorCode.FRONTMATTER_INVALID: "Invalid frontmatter format",
    ErrorCode.CONTENT_EMPTY: "Content cannot be empty",
    ErrorCode.DATE_INVALID: "Invalid date format (expected YYYY-MM-DD)",
    ErrorCode.ATTACHMENT_COPY_FAILED: "Failed to copy attachment file",
    # Search
    ErrorCode.INDEX_NOT_FOUND: "Search index not found",
    ErrorCode.SEARCH_FAILED: "Search operation failed",
    ErrorCode.QUERY_EMPTY: "Search query is empty",
    ErrorCode.NO_RESULTS: "No results found",
    # Weather
    ErrorCode.WEATHER_API_FAILED: "Weather API request failed",
    ErrorCode.WEATHER_TIMEOUT: "Weather API request timed out",
    ErrorCode.LOCATION_NOT_FOUND: "Location not found in weather service",
    ErrorCode.WEATHER_PARSE_ERROR: "Failed to parse weather data",
    # Edit
    ErrorCode.JOURNAL_NOT_FOUND: "Journal not found",
    ErrorCode.EDIT_CONFLICT: "Edit conflict detected",
    ErrorCode.FIELD_NOT_RECOGNIZED: "Field not recognized for editing",
    ErrorCode.NO_CHANGES_SPECIFIED: "No changes specified",
    # Index
    ErrorCode.INDEX_BUILD_FAILED: "Failed to build index",
    ErrorCode.INDEX_CORRUPTED: "Index is corrupted",
    ErrorCode.VECTOR_STORE_ERROR: "Vector store error",
    ErrorCode.FTS_INDEX_ERROR: "FTS index error",
}


def get_error_description(code: str) -> str:
    """Get human-readable description for an error code."""
    return ERROR_DESCRIPTIONS.get(code, "Unknown error")


def create_error_response(
    code: str,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    suggestion: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a standard error response without raising exception.

    Args:
        code: Error code from ErrorCode class
        message: Optional custom message (uses default if not provided)
        details: Optional details dict
        suggestion: Optional suggestion for user

    Returns:
        Standard error JSON response
    """
    if message is None:
        message = get_error_description(code)

    return LifeIndexError(code, message, details, suggestion).to_json()


def is_recoverable(code: str) -> bool:
    """
    Check if an error is recoverable (operation can continue).

    Recoverable errors:
    - Weather API failures (can skip weather)
    - No results (can return empty)

    Non-recoverable errors:
    - Permission denied
    - Path traversal
    - Write failures
    """
    strategy = LifeIndexError.RECOVERY_STRATEGIES.get(code, "ask_user")
    return strategy in ("skip_optional", "continue_empty")
