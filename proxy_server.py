import socket
import threading
import sys
import time

class ProxyServer:
    def __init__(self, host='0.0.0.0', port=15007, buffer_size=4096):
        self.host = host
        self.port = port
        self.buffer_size = buffer_size
        self.server_socket = None
        self.running = False
    
    def start(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            print(f"[INFO] 正向代理服务器已启动，监听地址: {self.host}:{self.port}")
            print(f"[INFO] 本地Win10设置代理为: {self.host}:{self.port}")
            
            while self.running:
                client_socket, client_address = self.server_socket.accept()
                print(f"[INFO] 接收到来自 {client_address} 的连接")
                client_thread = threading.Thread(target=self.handle_client, args=(client_socket, client_address))
                client_thread.daemon = True
                client_thread.start()
                
        except Exception as e:
            print(f"[ERROR] 服务器启动失败: {str(e)}")
            self.stop()
    
    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
            print("[INFO] 正向代理服务器已停止")
    
    def handle_client(self, client_socket, client_address):
        server_socket = None
        try:
            # 接收客户端请求
            request_data = client_socket.recv(self.buffer_size)
            if not request_data:
                client_socket.close()
                return
            
            # 解析请求
            request_str = request_data.decode('utf-8', errors='ignore')
            first_line = request_str.split('\n')[0]
            
            # 处理可能的格式问题
            line_parts = first_line.split(' ')
            if len(line_parts) < 3:
                client_socket.sendall(b'HTTP/1.1 400 Bad Request\r\n\r\n')
                client_socket.close()
                return
            
            method, url, version = line_parts
            
            # 处理CONNECT方法（HTTPS隧道）
            if method == 'CONNECT':
                print(f"[INFO] {client_address} 请求: CONNECT {url}")
                
                # 提取目标主机和端口
                if ':' in url:
                    target_hostname, target_port = url.split(':')
                    target_port = int(target_port)
                else:
                    target_hostname = url
                    target_port = 443
                
                # 连接目标服务器
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.connect((target_hostname, target_port))
                
                # 发送200 OK响应给客户端
                client_socket.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                
                # 开始双向数据转发
                self.forward_data(client_socket, server_socket)
                return
            
            # 处理HTTP请求
            # 处理完整URL和相对路径
            if url.startswith('http://'):
                # 完整URL格式
                target_url = url
                target_host = url.split('/')[2]
            else:
                # 相对路径格式，需要从请求头中获取Host
                host_line = next((line for line in request_str.split('\n') if line.startswith('Host: ')), None)
                if not host_line:
                    client_socket.sendall(b'HTTP/1.1 400 Bad Request\r\n\r\n')
                    client_socket.close()
                    return
                target_host = host_line.split(' ')[1]
                target_url = f'http://{target_host}{url}'
            
            print(f"[INFO] {client_address} 请求: {method} {target_url}")
            
            # 提取目标主机和端口
            if ':' in target_host:
                target_hostname, target_port = target_host.split(':')
                target_port = int(target_port)
            else:
                target_hostname = target_host
                target_port = 80
            
            # 连接目标服务器
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.connect((target_hostname, target_port))
            
            # 修改请求头，移除可能的代理相关头部
            modified_request = request_str
            if not url.startswith('http://'):
                # 如果是相对路径，需要构造完整的请求行
                modified_request = modified_request.replace(first_line, f"{method} {url} {version}")
            
            # 发送请求到目标服务器
            server_socket.sendall(modified_request.encode('utf-8', errors='ignore'))
            
            # 接收目标服务器响应并转发给客户端
            while True:
                response_data = server_socket.recv(self.buffer_size)
                if not response_data:
                    break
                client_socket.sendall(response_data)
            
        except socket.gaierror:
            print(f"[ERROR] 无法解析主机: {target_hostname}")
            client_socket.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
        except ConnectionRefusedError:
            print(f"[ERROR] 连接被拒绝: {target_hostname}:{target_port}")
            client_socket.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
        except Exception as e:
            print(f"[ERROR] 处理请求时出错: {str(e)}")
            try:
                client_socket.sendall(b'HTTP/1.1 500 Internal Server Error\r\n\r\n')
            except:
                pass
        finally:
            try:
                client_socket.close()
                if server_socket:
                    server_socket.close()
            except:
                pass
    
    def forward_data(self, client_socket, server_socket):
        """双向数据转发（用于HTTPS隧道）"""
        try:
            # 设置非阻塞模式
            client_socket.setblocking(False)
            server_socket.setblocking(False)
            
            while True:
                try:
                    # 从客户端读取数据并转发到服务器
                    client_data = client_socket.recv(self.buffer_size)
                    if client_data:
                        server_socket.sendall(client_data)
                    else:
                        break
                except socket.error:
                    pass
                
                try:
                    # 从服务器读取数据并转发到客户端
                    server_data = server_socket.recv(self.buffer_size)
                    if server_data:
                        client_socket.sendall(server_data)
                    else:
                        break
                except socket.error:
                    pass
        except Exception as e:
            print(f"[ERROR] 数据转发时出错: {str(e)}")
        finally:
            try:
                client_socket.close()
                server_socket.close()
            except:
                pass

def main():
    # 默认配置
    host = '0.0.0.0'
    port = 15007
    
    # 命令行参数解析
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help' or sys.argv[1] == '-h':
            print("使用方法:")
            print(f"  python {sys.argv[0]} [host] [port]")
            print("  默认值: host=0.0.0.0, port=15007")
            sys.exit(0)
        host = sys.argv[1]
        if len(sys.argv) > 2:
            try:
                port = int(sys.argv[2])
            except ValueError:
                print("[ERROR] 端口必须是整数")
                sys.exit(1)
    
    # 创建并启动代理服务器
    proxy = ProxyServer(host=host, port=port)
    try:
        proxy.start()
    except KeyboardInterrupt:
        print("\n[INFO] 接收到中断信号，正在停止服务器...")
        proxy.stop()

if __name__ == '__main__':
    main()
