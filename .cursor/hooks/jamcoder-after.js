#!/usr/bin/env node
process.stdout.write(JSON.stringify({}));
const r = require("http").request({ hostname:"127.0.0.1", port:18933, path:"/idle", method:"POST" }, () => process.exit());
r.on("error", () => process.exit());
r.end();
setTimeout(() => process.exit(), 500);
