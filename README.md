# Cloudflare Tunnel Manager

A Python CLI tool to manage Cloudflare tunnels with automatic cleanup and DNS configuration.

## Features

- Create and manage Cloudflare tunnels easily
- Two modes of operation:
  - `localhost`: Tunnel an existing local service
  - `folder`: Serve a folder via HTTP and tunnel it
- Automatic DNS configuration with fallback to tunnel ID
- Intelligent tunnel reuse and cleanup
- Automatic cleanup on exit with proper file deletion
- Simple command-line interface
- Smart file naming (tunnel-name.json instead of UUID.json)
- Comprehensive error handling and debugging output

## Prerequisites

- Python 3.8 or higher (tested with Python 3.12)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installed and in PATH
- A Cloudflare domain configured in your account
- Windows, macOS, or Linux operating system

## Installation

### Using pipx (recommended)

```bash
pipx install cloudflare-tunnelmanager
```

Note: to install pipx execute:

```bash
# Install pipx using pip
pip install --user pipx

# Add pipx to your PATH (this ensures pipx commands work from anywhere)
pipx ensurepath
```

### Using pip

```bash
pip install cloudflare-tunnelmanager
```

### From source

```bash
git clone <repository-url>
cd cloudflare-tunnelmanager
pip install .
```

## Usage

### Basic Commands

#### Tunnel a folder (serve via HTTP)

```bash
# Serve current directory
cloudflare-tunnelmanager folder yourdomain.com --port 8080

# Serve specific folder
cloudflare-tunnelmanager folder yourdomain.com --port 8080 --folder /path/to/folder

# With custom subdomain
cloudflare-tunnelmanager folder yourdomain.com --port 8080 --subdomain myapp
```

#### Tunnel an existing localhost service

```bash
# Tunnel a service running on localhost:3000
cloudflare-tunnelmanager localhost yourdomain.com --port 3000

# With custom subdomain
cloudflare-tunnelmanager localhost yourdomain.com --port 3000 --subdomain api
```

### Command Line Arguments

```
cloudflare-tunnelmanager <command> <domain> --port <port> [options]

Commands:
  localhost    Tunnel an existing localhost service
  folder       Serve a folder via HTTP and tunnel it

Required Arguments:
  command      Command to execute (localhost or folder)
  domain       The domain to use for the tunnel
  --port, -p   Port number to use

Optional Arguments:
  --folder, -f     Path to folder to serve (default: current directory, for folder command)
  --subdomain      Custom subdomain (defaults to folder name)
  --help           Show help message
```

### Examples

1. **Development server**: Tunnel a Next.js app running on port 3000
   ```bash
   cloudflare-tunnelmanager localhost mydomain.com --port 3000
   ```
   Creates tunnel: `nextjs-app.mydomain.com` → `localhost:3000`

2. **Static files**: Serve and tunnel a documentation folder
   ```bash
   cloudflare-tunnelmanager folder mydomain.com --port 8080 --folder ./docs
   ```
   Creates tunnel: `docs.mydomain.com` → HTTP server on port 8080

3. **Custom subdomain**: Use a specific subdomain
   ```bash
   cloudflare-tunnelmanager localhost mydomain.com --port 8000 --subdomain api
   ```
   Creates tunnel: `api.mydomain.com` → `localhost:8000`

4. **Current directory**: Serve current folder
   ```bash
   cloudflare-tunnelmanager folder mydomain.com --port 8080
   ```
   Creates tunnel based on current directory name

5. **Multiple services**: Run different services on different subdomains
   ```bash
   # Terminal 1 - API service
   cloudflare-tunnelmanager localhost mydomain.com --port 3000 --subdomain api
   
   # Terminal 2 - Frontend files
   cloudflare-tunnelmanager folder mydomain.com --port 8080 --subdomain app
   ```

## How It Works

1. **Tunnel Management**: Creates or reuses a Cloudflare tunnel with intelligent naming based on folder/subdomain
2. **File Cleanup**: Automatically removes existing tunnels with the same name to prevent conflicts
3. **DNS Configuration**: Configures DNS routing automatically with fallback to tunnel ID if name fails
4. **Service Handling**: 
   - For `folder` command: starts a Python HTTP server on the specified port
   - For `localhost` command: assumes service is already running and validates port availability
5. **Credentials Management**: Uses simplified naming (tunnel-name.json) instead of UUID-based files
6. **Browser Integration**: Opens the tunnel URL in your default browser once available
7. **Cleanup**: Handles comprehensive cleanup on exit (Ctrl+C) including process termination and file deletion

## Configuration

The tool creates configuration files in `~/.cloudflared/` directory:
- `config-tunnel-<tunnel-name>.yml`: Tunnel configuration with ingress rules
- `<tunnel-name>.json`: Tunnel credentials (simplified naming)

### Configuration File Structure

The generated config file includes:
- Tunnel name and credentials file reference
- Hostname mapping to local port
- Security settings (no-autoupdate, QUIC protocol)
- 404 fallback for unmatched routes

### Naming Convention

- **Tunnel names**: Based on folder name or specified subdomain
- **Credentials files**: `<tunnel-name>.json` (e.g., `myapp.json`)
- **Config files**: `config-tunnel-<tunnel-name>.yml` (e.g., `config-tunnel-myapp.yml`)
- **Domains**: `<subdomain>.<your-domain>` (e.g., `myapp.yourdomain.com`)

## Troubleshooting

### Common Issues

1. **cloudflared not found**: 
   - Install cloudflared and ensure it's in your PATH
   - Verify installation: `cloudflared --version`

2. **Tunnel creation failed**: 
   - Check your Cloudflare account permissions
   - Ensure you're authenticated: `cloudflared tunnel login`

3. **Port already in use**: 
   - Choose a different port with `--port` option
   - Stop the conflicting service, or use `localhost` command instead of `folder`

4. **DNS issues**: 
   - Wait a few minutes for DNS propagation
   - Check Cloudflare DNS settings in your dashboard
   - Tool automatically retries with tunnel ID if tunnel name fails

5. **Credentials file errors**:
   - Tool automatically handles file cleanup and recreation
   - Check permissions in `~/.cloudflared/` directory
   - Look for "Could not find credentials file" messages in output

6. **Tunnel starts but connection fails**:
   - Verify local service is running on specified port
   - Check firewall settings
   - Review cloudflared logs for "context canceled" errors

### Debug Output

The tool provides comprehensive debug output including:
- Tunnel ID and credentials file paths
- Command execution with blue highlighting
- Step-by-step process status
- Error details and suggested solutions

### Manual Cleanup

If automatic cleanup fails, manually remove:
- `~/.cloudflared/<tunnel-name>.json`
- `~/.cloudflared/config-tunnel-<tunnel-name>.yml`
- Run: `cloudflared tunnel delete -f <tunnel-name>`

## Version Information

Current version: **1.0.6**

### Recent Changes
- Improved tunnel creation and reuse logic
- Enhanced credentials file management with simplified naming
- Better error handling and debug output
- Automatic tunnel cleanup before creation to prevent conflicts
- Smart DNS routing with tunnel ID fallback
- Comprehensive file deletion with permission handling
- Support for both tunnel names and tunnel IDs in operations

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
