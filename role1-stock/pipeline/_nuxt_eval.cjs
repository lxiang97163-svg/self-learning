const path = require('path');
const fs = require('fs');
const raw = fs.readFileSync(path.join(__dirname, '_nuxt_expr.js'), 'utf8');
try {{
    const result = eval(raw);
    process.stdout.write(JSON.stringify(result));
}} catch(e) {{
    process.stderr.write("eval error: " + e.message + "\\n");
    process.exit(1);
}}
