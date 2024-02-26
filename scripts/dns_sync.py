import requests
import dns.resolver
import dns.update
import dns.query
import dns.tsigkeyring
import socket

def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org')
        return response.text.strip()
    except Exception as e:
        print("Error getting public IP:", e)
        return None

def update_dns_record(new_ip):
    dns_server = 'your_dns_server'  # Replace with your DNS server IP
    zone_name = 'radiswanson.org.'
    domain_name = 'hearts.radiswanson.org.'
    tsig_keyname = 'your_tsig_keyname'  # Replace with your TSIG key name
    tsig_secret = 'your_tsig_secret'  # Replace with your TSIG secret

    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [dns_server]

        keyring = dns.tsigkeyring.from_text({
            tsig_keyname: tsig_secret
        })

        old_ip = socket.gethostbyname(domain_name)

        if old_ip != new_ip:
            update = dns.update.Update(zone_name, keyring=keyring)
            update.replace(domain_name, 300, 'A', new_ip)

            response = dns.query.tcp(update, dns_server)
            print("DNS record updated successfully.")
        else:
            print("Public IP has not changed.")
    except Exception as e:
        print("Error updating DNS record:", e)

if __name__ == "__main__":
    public_ip = get_public_ip()
    if public_ip:
        print("Public IP:", public_ip)
        update_dns_record(public_ip)