"""Compiled scripts must wait for the document, as Babel standalone does."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node 없음')
class OptimizeTest(unittest.TestCase):
    def test_react_uses_browser_globals_with_new_babel_defaults(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
let opts;
const babel={transform:(code,o)=>{opts=o;return {code:'React.createElement("div")'};}};
c.window.Optimize.transpile(babel,'<div/>',{});
assert.equal(opts.presets[0][0], 'react');
assert.equal(opts.presets[0][1].runtime, 'classic');
c.window.Optimize.transpile(babel,'<div/>',{'data-presets':'react'});
assert.equal(opts.presets[0][1].runtime, 'classic');
"""
        subprocess.run(['node', '-e', script, str(Path(__file__).parents[1] / 'tvrelay/static/optimize.js')],
                       check=True, capture_output=True, text=True)

    def test_compiled_scripts_wait_for_dom_and_keep_global_scope(self):
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const context = vm.createContext({window: {}});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const compile = context.window.Optimize.compiledScript;
const ready = [], types = [];
context.document = {
  readyState: 'loading',
  addEventListener: (event, fn) => { assert.equal(event, 'DOMContentLoaded'); ready.push(fn); },
  createElement: () => ({}),
  head: {appendChild: s => {types.push(s.type); vm.runInContext(s.textContent, context);}}
};
function load(code, attrs={}) {
 const html = compile(code, attrs);
 assert.equal((html.match(/<\/script>/g)||[]).length, 1);
 vm.runInContext(html.slice(8, -9), context);
}
load('if (!document.root) throw Error("root missing"); var shared = "</script>";');
load('window.rendered = shared;');
assert.equal(context.window.rendered, undefined);
context.document.root = {};
context.document.readyState = 'interactive';
ready.forEach(fn => fn());
assert.equal(context.window.rendered, '</script>');
load('window.late = true;');
assert.equal(context.window.late, true);
load('window.moduleLoaded = true;', {'data-type': 'module'});
assert.equal(types.at(-1), 'module');
'''
        subprocess.run(['node', '-e', script, str(Path(__file__).parents[1] / 'tvrelay/static/optimize.js')],
                       check=True, capture_output=True, text=True)
