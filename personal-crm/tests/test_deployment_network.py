import ipaddress
import re
from pathlib import Path


def test_proxy_static_address_is_outside_dynamic_container_allocation():
    compose=Path('compose.production.yaml').read_text(encoding='utf-8')
    static=ipaddress.ip_address(re.search(r'ipv4_address:\s*([0-9.]+)',compose)[1])
    subnet=ipaddress.ip_network(re.search(r'subnet:\s*([0-9./]+)',compose)[1])
    allocation=re.search(r'ip_range:\s*([0-9./]+)',compose)
    assert allocation is not None,'Reserve a dynamic range so API cannot claim the trusted Caddy static IP first'
    dynamic=ipaddress.ip_network(allocation[1])
    assert dynamic.subnet_of(subnet) and static in subnet and static not in dynamic
    image=Path('Dockerfile.production').read_text(encoding='utf-8')
    assert '"--forwarded-allow-ips", "'+str(static)+'"' in image
