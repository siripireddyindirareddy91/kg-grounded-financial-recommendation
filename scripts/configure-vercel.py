"""Supply stable session secret through stdin without printing or saving its value."""
import secrets,subprocess,shutil
cli=shutil.which('vercel.cmd') or shutil.which('vercel')
result=subprocess.run([cli,'env','add','JWT_SECRET_KEY','production'],input=secrets.token_hex(48)+'\n',text=True,capture_output=True)
print('Production session secret configured' if result.returncode==0 else 'Session secret configuration failed: '+result.stderr)
