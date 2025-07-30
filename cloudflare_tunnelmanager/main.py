#!/usr/bin/env python3
"""
Cloudflare Tunnel Manager
A Python script to manage Cloudflare tunnels with automatic cleanup and DNS configuration.
"""

__version__ = "2.0.0"

import argparse
import atexit
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import requests


class CloudflareTunnelManager:
    """Manages Cloudflare tunnels with automatic cleanup and configuration."""
    
    def __init__(self, command: str, port: int, folder: Optional[str] = None, subdomain: Optional[str] = None) -> None:
        """
        Initialize the tunnel manager.
        
        Args:
            command: Command type ('localhost' or 'folder')
            port: Port number to use
            folder: Folder path for 'folder' command
            subdomain: Optional subdomain, defaults to folder name
        """
        # Get domain from Cloudflare authentication
        self.domain = self.get_cloudflare_domain()
        if not self.domain:
            print("Error: Could not determine domain from Cloudflare authentication.")
            print("Please run 'cloudflared login' and select your domain.")
            sys.exit(1)
        
        self.command = command
        self.port = port
        self.folder_path = folder
        
        # Determine tunnel naming
        if command == "folder" and folder:
            if folder == ".":
                # Use the current directory name when folder is "."
                self.folder_name = Path.cwd().name
            else:
                self.folder_name = Path(folder).name
        else:
            self.folder_name = Path(__file__).parent.name
            
        self.tunnel_name = self.folder_name
        self.subdomain = subdomain or self.folder_name
        self.full_domain = f"{self.subdomain}.{self.domain}"
        
        # Setup paths
        self.cloudflared_dir = Path.home() / ".cloudflared"
        self.config_file = self.cloudflared_dir / f"config-tunnel-{self.tunnel_name}.yml"
        
        # Process references
        self.python_process: Optional[subprocess.Popen] = None
        self.cloudflared_process: Optional[subprocess.Popen] = None
        
        # Local port for internal use
        self.local_port = port
        
        # Ensure .cloudflared directory exists
        self.cloudflared_dir.mkdir(exist_ok=True)
        if not self.cloudflared_dir.exists():
            print(f"Created .cloudflared directory: {self.cloudflared_dir}")
    
    def get_cloudflare_domain(self) -> Optional[str]:
        """
        Get the domain from Cloudflare authentication by reading cert.pem and making API call.
        
        Returns:
            Domain name if found, None if error
        """
        try:
            # Setup paths
            cloudflared_dir = Path.home() / ".cloudflared"
            cert_file = cloudflared_dir / "cert.pem"
            
            if not cert_file.exists():
                print(f"Cloudflare certificate not found at: {cert_file}")
                print("Please run 'cloudflared login' to authenticate with Cloudflare.")
                return None
            
            # Read and decode the certificate
            cert_content = cert_file.read_text().strip()
            
            # Extract the base64 token between the BEGIN/END markers
            lines = cert_content.split('\n')
            token_lines = []
            in_token = False
            
            for line in lines:
                if "-----BEGIN ARGO TUNNEL TOKEN-----" in line:
                    in_token = True
                    continue
                elif "-----END ARGO TUNNEL TOKEN-----" in line:
                    break
                elif in_token:
                    token_lines.append(line.strip())
            
            if not token_lines:
                print("Could not find valid token in cert.pem")
                return None
            
            # Decode the base64 token
            token_b64 = ''.join(token_lines)
            try:
                token_json = base64.b64decode(token_b64).decode('utf-8')
                token_data = json.loads(token_json)
            except Exception as e:
                print(f"Error decoding token: {e}")
                return None
            
            # Extract required fields
            zone_id = token_data.get('zoneID')
            api_token = token_data.get('apiToken')
            account_id = token_data.get('accountID')
            
            if not all([zone_id, api_token]):
                print("Missing required fields in token (zoneID, apiToken)")
                return None
            
            print(f"Found Cloudflare authentication:")
            print(f"  Zone ID: {zone_id}")
            print(f"  Account ID: {account_id}")
            
            # Make API call to get zone information
            url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}"
            headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                print(f"API call failed with status {response.status_code}: {response.text}")
                return None
            
            data = response.json()
            if not data.get('success'):
                print(f"API call unsuccessful: {data.get('errors', 'Unknown error')}")
                return None
            
            result = data.get('result', {})
            domain = result.get('name')
            status = result.get('status')
            account_name = result.get('account', {}).get('name', 'Unknown')
            
            if domain:
                print(f"  Domain: {domain}")
                print(f"  Status: {status}")
                print(f"  Account: {account_name}")
                return domain
            else:
                print("Domain name not found in API response")
                return None
                
        except Exception as e:
            print(f"Error getting Cloudflare domain: {e}")
            return None
    
    def get_available_port(self, start_port: int = 8100, end_port: int = 9000) -> int:
        """
        Find an available TCP port starting from start_port.
        
        Args:
            start_port: Port to start checking from
            end_port: Maximum port to check
            
        Returns:
            Available port number
            
        Raises:
            RuntimeError: If no available ports found in range
        """
        for port in range(start_port, end_port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind(('localhost', port))
                    return port
                except OSError:
                    continue
        
        raise RuntimeError(f"No available ports found in range {start_port} to {end_port}")
    
    def create_cloudflared_config(self, config_path: Path, tunnel_name: str, 
                                hostname: str, local_port: int) -> bool:
        """
        Create cloudflared configuration file.
        
        Args:
            config_path: Path to config file
            tunnel_name: Name of the tunnel
            hostname: Hostname for the tunnel
            local_port: Local port to forward to
            
        Returns:
            True if successful, False otherwise
        """
        # Find existing credentials file directly in .cloudflared directory
        credentials_file = self.find_tunnel_credentials_file(tunnel_name)
        if not credentials_file:
            print(f"Error: Could not find credentials file for tunnel {tunnel_name}")
            return False
        
        config_content = f"""tunnel: {tunnel_name}
credentials-file: {credentials_file}

ingress:
  - hostname: {hostname}
    service: http://localhost:{local_port}
  - service: http_status:404

# Security settings
no-autoupdate: true
protocol: quic
"""
        
        try:
            config_path.write_text(config_content, encoding='utf-8')
            print(f"Created config file: {config_path}")
            print(f"Using credentials file: {credentials_file}")
            return True
        except Exception as e:
            print(f"Error creating config file: {e}")
            return False
    
    def find_tunnel_credentials_file(self, tunnel_name: str) -> Optional[Path]:
        """
        Find the credentials file for a tunnel.
        
        Args:
            tunnel_name: Name of the tunnel
            
        Returns:
            Path to credentials file or None if not found
        """
        # Check for tunnel-name.json (new naming convention)
        expected_file = self.cloudflared_dir / f"{tunnel_name}.json"
        if expected_file.exists():
            return expected_file
        
        return None
    
    def test_cloudflared_installed(self) -> bool:
        """Check if cloudflared is installed and available in PATH."""
        return shutil.which("cloudflared") is not None
    
    def run_command(self, cmd: List[str], show_blue: bool = False, 
                   capture_output: bool = False) -> subprocess.CompletedProcess:
        """
        Run a command with optional blue output display.
        
        Args:
            cmd: Command and arguments to run
            show_blue: Whether to display command in blue
            capture_output: Whether to capture stdout/stderr
            
        Returns:
            CompletedProcess result
        """
        if show_blue:
            # ANSI color codes: blue text
            print(f"\033[94m{' '.join(cmd)}\033[0m")
        
        return subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=False
        )
    
    def remove_cloudflare_tunnel(self, tunnel_name: str) -> None:
        """
        Clean up and remove Cloudflare tunnel by name and delete associated files.
        
        Args:
            tunnel_name: Name of the tunnel to remove
        """
        try:
            print(f"Cleaning up tunnel: {tunnel_name}")
            
            # Delete tunnel by name (simplified approach)
            print("Deleting tunnel...")
            delete_result = self.run_command(
                ["cloudflared", "tunnel", "delete", "-f", tunnel_name],
                show_blue=True
            )
            
            if delete_result.returncode == 0:
                print(f"✅ Tunnel {tunnel_name} deleted successfully")
            else:
                print(f"⚠️ Delete command completed for tunnel {tunnel_name}")
            
            # Remove associated files
            self._remove_tunnel_files(tunnel_name)
                    
        except Exception as e:
            print(f"❌ Error during tunnel cleanup for {tunnel_name}: {e}")
    
    def _remove_tunnel_files(self, tunnel_name: str) -> None:
        """Remove JSON credentials file and YML config file for a tunnel."""
        import stat
        import time
        
        # Remove JSON credentials file
        json_file = self.cloudflared_dir / f"{tunnel_name}.json"
        if json_file.exists():
            try:
                # First try normal deletion
                json_file.unlink()
                print(f"Removed credentials file: {json_file}")
            except PermissionError:
                try:
                    # Try to change file permissions and delete
                    os.chmod(json_file, stat.S_IWRITE)
                    json_file.unlink()
                    print(f"Removed credentials file (after permission change): {json_file}")
                except Exception as e:
                    try:
                        # Wait a moment and try again (file might be locked temporarily)
                        time.sleep(1)
                        json_file.unlink()
                        print(f"Removed credentials file (after delay): {json_file}")
                    except Exception as e2:
                        print(f"Could not remove credentials file: {e2}")
                        print(f"You may need to manually delete: {json_file}")
            except Exception as e:
                print(f"Could not remove credentials file: {e}")
        
        # Remove YML config file  
        yml_file = self.cloudflared_dir / f"config-tunnel-{tunnel_name}.yml"
        if yml_file.exists():
            try:
                yml_file.unlink()
                print(f"Removed config file: {yml_file}")
            except Exception as e:
                print(f"Could not remove config file: {e}")
    
    def create_or_reuse_tunnel(self, tunnel_name: str) -> bool:
        """
        Create a new tunnel or reuse an existing one.
        
        Args:
            tunnel_name: Name of the tunnel
            
        Returns:
            True if successful, False otherwise
        """
        try:
            tunnel_id: Optional[str] = None
            
            # Check if tunnel credentials already exist
            credentials_file = self.find_tunnel_credentials_file(tunnel_name)
            if credentials_file and credentials_file.exists():
                print(f"Tunnel {tunnel_name} already exists - reusing it")
                
                # Get tunnel ID from existing credentials
                try:
                    with open(credentials_file, 'r') as f:
                        tunnel_info = json.load(f)
                        tunnel_id = tunnel_info.get("TunnelID")
                        print(f"Found existing tunnel ID: {tunnel_id}")
                except Exception as e:
                    print(f"Could not read existing tunnel credentials, creating new tunnel: {e}")
            else:
                # Create new tunnel - first remove any existing tunnel with the same name
                print(f"Creating tunnel: {tunnel_name}")
                
                # Remove existing tunnel with same name if it exists
                print("Checking for existing tunnel with same name...")
                self.remove_cloudflare_tunnel(tunnel_name)
                
                result = self.run_command(
                    ["cloudflared", "tunnel", "create", tunnel_name],
                    show_blue=True,
                    capture_output=True
                )
                
                if result.returncode != 0:
                    print(f"Failed to create tunnel {tunnel_name}.")
                    if result.stderr:
                        print(f"Error: {result.stderr}")
                    return False
                
                print(f"Tunnel {tunnel_name} created successfully.")
                
                # Print the raw output for debugging
                print(f"Debug - Command stdout: {result.stdout}")
                print(f"Debug - Command stderr: {result.stderr}")
                
                # Parse the output to find the credentials file path
                tunnel_id_file = None
                output_text = ""
                
                # Check both stderr and stdout for the credentials file path
                if result.stderr:
                    output_text += result.stderr
                if result.stdout:
                    output_text += result.stdout
                    
                if output_text:
                    # Look for the credentials file path in the output
                    import re
                    match = re.search(r'Tunnel credentials written to (.+\.json)', output_text)
                    if match:
                        credentials_path = match.group(1)
                        tunnel_id_file = Path(credentials_path)
                        print(f"Found credentials file: {tunnel_id_file}")
                        
                        # Get tunnel ID from the file
                        try:
                            with open(tunnel_id_file, 'r') as f:
                                tunnel_info = json.load(f)
                                tunnel_id = tunnel_info.get("TunnelID")
                                print(f"Found tunnel ID: {tunnel_id}")
                        except Exception as e:
                            print(f"Could not read tunnel ID from credentials: {e}")
                    else:
                        print(f"Debug: Could not find credentials path in output.")
                        print(f"Full output text: '{output_text}'")
                        
                        # Try to extract tunnel ID from the output directly
                        tunnel_id_match = re.search(r'Created tunnel .+ with id ([a-f0-9-]{36})', output_text)
                        if tunnel_id_match:
                            tunnel_id = tunnel_id_match.group(1)
                            print(f"Extracted tunnel ID from output: {tunnel_id}")
                            # Construct expected file path
                            tunnel_id_file = self.cloudflared_dir / f"{tunnel_id}.json"
                            print(f"Expected credentials file: {tunnel_id_file}")
                        else:
                            print("Could not extract tunnel ID from output either")
                
                if tunnel_id_file and tunnel_id_file.exists():
                    # Rename the file from <TunnelID>.json to <tunnel_name>.json
                    new_credentials_file = self.cloudflared_dir / f"{tunnel_name}.json"
                    tunnel_id_file.rename(new_credentials_file)
                    print(f"Renamed credentials file from {tunnel_id_file.name} to {new_credentials_file.name}")
                    credentials_file = new_credentials_file
                else:
                    print(f"Warning: Could not find credentials file for {tunnel_name}")
                    return False
            
            # Set up DNS route (always do this to ensure it's current)
            print(f"Setting up DNS route for {self.full_domain}...")
            route_result = self.run_command([
                "cloudflared", "tunnel", "route", "dns", "--overwrite-dns",
                tunnel_name, self.full_domain
            ], show_blue=True)
            
            if route_result.returncode == 0:
                print(f"DNS route configured successfully for {self.full_domain}")
            elif tunnel_id:
                # Try with tunnel ID if name failed
                route_result2 = self.run_command([
                    "cloudflared", "tunnel", "route", "dns", "--overwrite-dns",
                    tunnel_id, self.full_domain
                ], show_blue=True)
                
                if route_result2.returncode == 0:
                    print("DNS route configured successfully using tunnel ID")
                else:
                    print("DNS route configuration failed. Manual setup required:")
                    print(f"Go to Cloudflare dashboard > DNS settings for '{self.domain}'")
                    print(f"Add CNAME record: {self.subdomain} -> {tunnel_id}.cfargotunnel.com")
            
            # Create config file now that we have credentials
            if not self.create_cloudflared_config(
                self.config_file, self.tunnel_name, self.full_domain, self.local_port
            ):
                print("Failed to create config file.")
                return False
            
            return True
            
        except Exception as e:
            print(f"Error creating/reusing tunnel {tunnel_name}: {e}")
            return False
    
    def wait_for_url(self, url: str, timeout_seconds: int = 120) -> bool:
        """
        Wait for a URL to become reachable.
        
        Args:
            url: URL to check
            timeout_seconds: Maximum time to wait
            
        Returns:
            True if URL becomes reachable, False if timeout
        """
        end_time = datetime.now() + timedelta(seconds=timeout_seconds)
        attempt_count = 0
        
        while datetime.now() < end_time:
            attempt_count += 1
            try:
                print(f"Attempt {attempt_count}: Checking {url}...")
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    print("Success! Site is responding with status code 200.")
                    return True
            except Exception as e:
                error_message = str(e)
                print(f"Attempt {attempt_count} failed: {error_message}")
                
                # Check if it's a DNS resolution issue
                if "name resolution" in error_message.lower() or "dns" in error_message.lower():
                    print("DNS resolution issue detected. Checking local server...")
                    try:
                        local_response = requests.get(f"http://localhost:{self.local_port}", timeout=2)
                        if local_response.status_code == 200:
                            print(f"Local server is working on port {self.local_port}")
                    except Exception as local_e:
                        print(f"Local server check failed: {local_e}")
                
                time.sleep(5)
        
        print(f"Failed to reach {url} after {attempt_count} attempts over {timeout_seconds} seconds.")
        return False
    
    def cleanup(self) -> None:
        """Clean up processes and files."""
        print("Cleaning up...")
        
        # Stop processes if they're still running
        if self.python_process and self.python_process.poll() is None:
            try:
                self.python_process.terminate()
                self.python_process.wait(timeout=5)
                print("Python server stopped.")
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.python_process.kill()
                    print("Python server force stopped.")
                except ProcessLookupError:
                    pass
        
        if self.cloudflared_process and self.cloudflared_process.poll() is None:
            try:
                self.cloudflared_process.terminate()
                self.cloudflared_process.wait(timeout=5)
                print("Cloudflared stopped.")
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.cloudflared_process.kill()
                    print("Cloudflared force stopped.")
                except ProcessLookupError:
                    pass
        
        # Clean up tunnel and associated files
        self.remove_cloudflare_tunnel(self.tunnel_name)
        
        # Note: Files are cleaned up in remove_cloudflare_tunnel method
    
    def run(self) -> None:
        """Main execution method."""
        print(f"Cloudflare Tunnel Manager v{__version__}")
        
        # Set working directory based on command
        if self.command == "folder" and self.folder_path:
            folder_path = Path(self.folder_path).resolve()
            if not folder_path.exists():
                print(f"Error: Folder '{folder_path}' does not exist.")
                sys.exit(1)
            if not folder_path.is_dir():
                print(f"Error: '{folder_path}' is not a directory.")
                sys.exit(1)
            os.chdir(folder_path)
            print(f"Serving folder: {folder_path}")
        else:
            # For localhost command, stay in current directory
            os.chdir(Path(__file__).parent)
        
        print(f"Using tunnel name: {self.tunnel_name}")
        print(f"Local port: {self.local_port}")
        print(f"Full domain: {self.full_domain}")
        print(f"Config file: {self.config_file}")
        print(f"Command: {self.command}")
        
        # Check if cloudflared is installed
        if not self.test_cloudflared_installed():
            print("Error: cloudflared is not installed or not in PATH.")
            print("Please download and install cloudflared from: "
                  "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            print("After installation, make sure cloudflared is available in your PATH.")
            sys.exit(1)
        
        # Create or reuse tunnel (this will also create the config file)
        if not self.create_or_reuse_tunnel(self.tunnel_name):
            print("Failed to create/reuse tunnel. Exiting.")
            sys.exit(1)
        
        # Register cleanup handlers
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        
        # Start services based on command
        if self.command == "folder":
            # Start Python HTTP server for folder serving
            print(f"Starting HTTP server on port {self.local_port} for folder serving...")
            self.python_process = subprocess.Popen([
                sys.executable, "-m", "http.server", str(self.local_port)
            ])
        elif self.command == "localhost":
            # For localhost command, we assume a service is already running on the port
            print(f"Tunneling localhost:{self.local_port} (assuming service is already running)")
            # Check if port is actually in use
            if not self._is_port_in_use(self.local_port):
                print(f"Warning: No service appears to be running on localhost:{self.local_port}")
                print("Make sure your service is running before starting the tunnel.")
        
        # Start cloudflared tunnel
        print(f"\033[94mcloudflared tunnel --config \"{self.config_file}\" run\033[0m")
        self.cloudflared_process = subprocess.Popen([
            "cloudflared", "tunnel", "--config", str(self.config_file), "run"
        ])
        
        # Wait for the site to become available
        url_to_open = f"https://{self.full_domain}/"
        print(f"Waiting for {url_to_open} to become available...")
        
        if self.wait_for_url(url_to_open, timeout_seconds=60):
            webbrowser.open(url_to_open)
            print(f"Opened {url_to_open} in default browser.")
        else:
            print(f"Timed out waiting for {url_to_open}.")
            print(f"You can try manually opening: {url_to_open}")
            print(f"Or check the local server at: http://localhost:{self.local_port}")
        
        # Wait for processes to exit
        print("Press Ctrl+C to stop everything...")
        
        try:
            # Wait for cloudflared process to exit (and python process if it exists)
            while self.cloudflared_process.poll() is None:
                if (self.python_process and 
                    self.python_process.poll() is not None):
                    print("HTTP server stopped unexpectedly.")
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nProcesses interrupted.")
    
    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is currently in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.connect(('localhost', port))
                return True
            except (socket.error, ConnectionRefusedError):
                return False


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Cloudflare Tunnel Manager - Create and manage Cloudflare tunnels"
    )
    
    # Add command as first positional argument
    parser.add_argument(
        'command',
        choices=['localhost', 'folder'],
        help='Command to execute: localhost (tunnel existing service) or folder (serve folder)'
    )
    
    # Add port parameter (required)
    parser.add_argument(
        '--port', '-p',
        type=int,
        required=True,
        help='Port number to use'
    )
    
    # Add folder parameter (only used with folder command)
    parser.add_argument(
        '--folder', '-f',
        default='.',
        help='Path to the folder to serve (default: current directory, only used with folder command)'
    )
    
    # Add optional subdomain parameter
    parser.add_argument(
        '--subdomain',
        help='Optional subdomain (defaults to folder name)'
    )
    
    args = parser.parse_args()
    
    # Create and run tunnel manager based on command
    if args.command == 'localhost':
        manager = CloudflareTunnelManager(
            command='localhost',
            port=args.port,
            subdomain=args.subdomain
        )
    elif args.command == 'folder':
        manager = CloudflareTunnelManager(
            command='folder',
            port=args.port,
            folder=args.folder,
            subdomain=args.subdomain
        )
    else:
        parser.print_help()
        sys.exit(1)
    
    manager.run()


if __name__ == "__main__":
    main()
