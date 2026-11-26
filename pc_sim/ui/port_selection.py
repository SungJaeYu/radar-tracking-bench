"""Conservative port suggestions from USB descriptions; never open a port."""


def suggest_ports(ports) -> dict[str, str | None]:
    candidates = {'data': [], 'console': []}
    for port in ports:
        description = (port.description or '').lower().replace('-', '').replace('_', '')
        if 'stlink' in description or 'stm32' in description:
            candidates['console'].append(port.device)
        elif any(name in description for name in ('usb uart', 'usbuart', 'usb serial',
                                                   'usbserial', 'cp210', 'ch340', 'ch341', 'ft232')):
            candidates['data'].append(port.device)
    return {role: devices[0] if len(devices) == 1 else None
            for role, devices in candidates.items()}
