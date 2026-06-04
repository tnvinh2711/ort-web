const express = require('express');
const _ = require('lodash');
const app = express();

// CVE-2020-8203: lodash prototype pollution
// CVE-2020-7598: minimist prototype pollution
// CVE-2019-10744: lodash defaultsDeep
// CVE-2020-28168: axios SSRF
// CVE-2022-0235: node-fetch

app.get('/merge', (req, res) => {
    const base = {};
    // Vulnerable merge — attacker can pollute Object.prototype
    const result = _.merge(base, JSON.parse(req.query.payload || '{}'));
    res.json(result);
});

app.listen(3000);
