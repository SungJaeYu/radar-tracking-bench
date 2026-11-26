"""Presentation-only helpers; never alter recorded UART data."""


class AnsiFilter:
    """Remove terminal escape sequences, including those split across reads."""

    def __init__(self) -> None:
        self.state = 'text'

    def feed(self, text: str) -> str:
        output = []
        for char in text:
            if self.state == 'text':
                if char == '\x1b':
                    self.state = 'escape'
                elif char != '\r':
                    output.append(char)
            elif self.state == 'escape':
                self.state = 'csi' if char == '[' else 'osc' if char == ']' else 'text'
            elif self.state == 'csi':
                if '@' <= char <= '~':
                    self.state = 'text'
            elif self.state == 'osc':
                if char == '\x07':
                    self.state = 'text'
                elif char == '\x1b':
                    self.state = 'osc_end'
            elif self.state == 'osc_end':
                self.state = 'text' if char == '\\' else 'osc'
        return ''.join(output)
