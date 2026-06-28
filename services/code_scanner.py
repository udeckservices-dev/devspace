"""
code_scanner.py
---------------
Scans deployed projects for code quality issues and security vulnerabilities.
Uses bandit (Python security), npm audit (Node.js), and pylint (Python quality).
"""

import os
import re
import json
import subprocess
import tempfile
from datetime import datetime


class CodeScanner:
    """Static analysis scanner for deployed projects."""

    SCANNERS = {
        'python': ['bandit', 'pylint'],
        'node':   ['npm_audit'],
    }

    # ── Public API ──

    @staticmethod
    def scan_project(project):
        """
        Run all applicable scanners on a project directory.
        Returns dict: { 'scanner_name': { 'issues': [...], 'summary': {...} } }
        """
        deploy_path = project.get('deploy_path') or project.deploy_path
        language    = (project.get('language') or project.language or '').lower()
        name        = project.get('name') or project.name

        if not os.path.isdir(deploy_path):
            return {'error': f'Deploy path not found: {deploy_path}'}

        scanners = CodeScanner.SCANNERS.get(language, [])
        results  = {}

        for scanner in scanners:
            try:
                fn = getattr(CodeScanner, f'_scan_{scanner}', None)
                if fn:
                    results[scanner] = fn(deploy_path, name)
            except Exception as e:
                results[scanner] = {'error': str(e)}

        # If no scanner ran, try to detect
        if not results:
            results['generic'] = CodeScanner._scan_fallback(deploy_path)

        return results

    @staticmethod
    def available():
        """Check which scanning tools are installed on this system."""
        avail = {}
        for tool in ['bandit', 'pylint', 'npm']:
            try:
                subprocess.run([tool, '--version'], capture_output=True, timeout=10)
                avail[tool] = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                avail[tool] = False
        return avail

    # ── Python: Bandit (security) ──

    @staticmethod
    def _scan_bandit(deploy_path, project_name):
        """Run bandit security scanner on Python files."""
        try:
            result = subprocess.run(
                ['bandit', '-r', deploy_path, '-f', 'json', '--quiet'],
                capture_output=True, text=True, timeout=120
            )
            data = json.loads(result.stdout) if result.stdout else {}
        except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
            return {'error': 'bandit not installed or timed out'}

        issues = []
        for metric in data.get('results', []):
            issues.append({
                'type':     'security',
                'scanner':  'bandit',
                'severity': metric.get('issue_severity', 'MEDIUM').upper(),
                'confidence': metric.get('issue_confidence', 'MEDIUM').upper(),
                'title':    metric.get('test_name', 'Unknown'),
                'message':  metric.get('issue_text', ''),
                'file':     metric.get('filename', '').replace(deploy_path, ''),
                'line':     metric.get('line_number', 0),
                'code':     metric.get('code', ''),
            })

        totals = data.get('metrics', {}).get('_totals', {})
        return {
            'issues': issues,
            'summary': {
                'total':   totals.get('CONFIDENCE_HIGH', 0) + totals.get('CONFIDENCE_MEDIUM', 0),
                'high':    totals.get('SEVERITY_HIGH', 0),
                'medium':  totals.get('SEVERITY_MEDIUM', 0),
                'low':     totals.get('SEVERITY_LOW', 0),
            }
        }

    # ── Python: Pylint (code quality) ──

    @staticmethod
    def _scan_pylint(deploy_path, project_name):
        """Run pylint for code quality metrics."""
        py_files = []
        for root, dirs, files in os.walk(deploy_path):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'venv', 'node_modules')]
            for f in files:
                if f.endswith('.py'):
                    py_files.append(os.path.join(root, f))

        if not py_files:
            return {'issues': [], 'summary': {'total': 0, 'high': 0, 'medium': 0, 'low': 0}}

        score = 10.0
        issues = []

        try:
            result = subprocess.run(
                ['pylint', '--output-format=json'] + py_files[:50],
                capture_output=True, text=True, timeout=120
            )
            data = json.loads(result.stdout) if result.stdout else []
        except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
            data = []

        for item in data:
            message_id = item.get('message-id', '')
            severity_map = {
                'C': 'low', 'R': 'low', 'W': 'medium',
                'E': 'high', 'F': 'high'
            }
            cat = (item.get('type') or '')[:1].upper()
            sev = severity_map.get(cat, 'medium')

            issues.append({
                'type':     'quality',
                'scanner':  'pylint',
                'severity': sev.upper(),
                'confidence': 'HIGH',
                'title':    message_id,
                'message':  item.get('message', ''),
                'file':     item.get('path', '').replace(deploy_path, ''),
                'line':     item.get('line', 0),
                'code':     '',
            })

        # Parse score from stderr
        score_match = re.search(r'Your code has been rated at ([\d.]+)', result.stderr)
        if score_match:
            score = float(score_match.group(1))

        return {
            'issues': issues,
            'summary': {
                'total':      len(issues),
                'high':       sum(1 for i in issues if i['severity'] == 'HIGH'),
                'medium':     sum(1 for i in issues if i['severity'] == 'MEDIUM'),
                'low':        sum(1 for i in issues if i['severity'] == 'LOW'),
                'pylint_score': score,
            }
        }

    # ── Node.js: npm audit ──

    @staticmethod
    def _scan_npm_audit(deploy_path, project_name):
        """Run npm audit for dependency vulnerabilities."""
        pkg_json = os.path.join(deploy_path, 'package.json')
        if not os.path.isfile(pkg_json):
            return {'issues': [], 'summary': {'total': 0, 'high': 0, 'medium': 0, 'low': 0}}

        try:
            result = subprocess.run(
                ['npm', 'audit', '--json', '--prefix', deploy_path],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode in (0, 1):
                data = json.loads(result.stdout) if result.stdout else {}
            else:
                data = {}
        except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
            return {'error': 'npm not installed or timed out'}

        issues = []
        advisories = data.get('advisories', {})
        for adv_id, adv in advisories.items():
            severity = (adv.get('severity') or 'medium').upper()
            issues.append({
                'type':     'dependency',
                'scanner':  'npm_audit',
                'severity': severity,
                'confidence': 'HIGH',
                'title':    adv.get('title', 'Unknown'),
                'message':  adv.get('overview', ''),
                'file':     'package.json',
                'line':     0,
                'code':     '',
                'cve':      adv.get('cves', []),
                'fix':      adv.get('recommendation', ''),
            })

        meta = data.get('metadata', {})
        vulns = meta.get('vulnerabilities', {})
        return {
            'issues': issues,
            'summary': {
                'total':      sum(vulns.values()),
                'high':       vulns.get('high', 0),
                'medium':     vulns.get('medium', 0),
                'low':        vulns.get('low', 0),
            }
        }

    # ── Fallback: basic file check ──

    @staticmethod
    def _scan_fallback(deploy_path):
        """Basic scan when no language-specific scanner is available."""
        issues = []
        findings = []

        # Check for common bad patterns
        patterns = {
            'hardcoded_password': (r'password\s*=\s*["\']([^"\']+)["\']', 'MEDIUM'),
            'hardcoded_secret':   (r'(api_key|secret|token)\s*=\s*["\']([^"\']+)["\']', 'HIGH'),
            'debug_true':         (r'debug\s*=\s*True', 'MEDIUM'),
            'allow_all_hosts':    (r'ALLOWED_HOSTS\s*=\s*\[\s*"\*', 'HIGH'),
        }

        for root, dirs, files in os.walk(deploy_path):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'venv', 'node_modules')]
            for fname in files:
                if fname.endswith(('.py', '.js', '.php', '.env', '.env.example', '.yml', '.yaml')):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                for name, (pattern, sev) in patterns.items():
                                    if re.search(pattern, line, re.IGNORECASE):
                                        findings.append({
                                            'type': 'security',
                                            'scanner': 'basic',
                                            'severity': sev,
                                            'confidence': 'MEDIUM',
                                            'title': name.replace('_', ' ').title(),
                                            'message': f'Potential {name.replace("_", " ")} detected',
                                            'file': fpath.replace(deploy_path, ''),
                                            'line': i,
                                            'code': line.strip()[:100],
                                        })
                    except (IOError, OSError):
                        pass

        return {
            'issues': findings,
            'summary': {
                'total':  len(findings),
                'high':   sum(1 for i in findings if i['severity'] == 'HIGH'),
                'medium': sum(1 for i in findings if i['severity'] == 'MEDIUM'),
                'low':    sum(1 for i in findings if i['severity'] == 'LOW'),
            }
        }
