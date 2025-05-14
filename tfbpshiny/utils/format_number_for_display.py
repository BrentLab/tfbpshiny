import collections.abc


def format_to_sci_notation(data_input):
    """
    Formats a number or an iterable of numbers into scientific notation with two decimal
    places.

    Args:
      data_input: A single number (int or float) or
      an iterable (e.g., list, tuple)
                  of numbers to format. Avoid passing strings
                  or iterables of non-numbers.

    Returns:
      If data_input is a single number, returns a string
      representing the number
      in scientific notation (e.g., "1.23e+04").
      If data_input is an iterable of numbers, returns a list of strings,
      each formatted in scientific notation.
      Returns the original input or raises TypeError for
      unsupported types if formatting fails.

    """
    if isinstance(data_input, (int, float)):
        return f"{data_input:.2e}"
    elif isinstance(data_input, collections.abc.Iterable) and not isinstance(
        data_input, (str, bytes)
    ):
        try:
            return [f"{n:.2e}" for n in data_input]
        except TypeError:
            # Handle cases where items in iterable are not numbers
            raise TypeError(
                "If providing an iterable, all items must be numbers " "(int or float)."
            )
    else:
        # For unsupported types, it's often better to indicate an issue.
        # Depending on usage, you might return data_input as is, or None.
        # Raising an error is explicit about misuse.
        raise TypeError(
            "Input must be a number (int or float) or an iterable of numbers "
            "(e.g., list, tuple)."
        )
