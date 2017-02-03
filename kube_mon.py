#!/usr/bin/env python
from optparse import OptionParser
import datetime
import shlex
import subprocess
import logging
import re
import sys

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# console logging
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
cformat = logging.Formatter('%(message)s')
# cformat = logging.Formatter('%(levelname)s: %(name)s - %(message)s')
ch.setFormatter(cformat)
logger.addHandler(ch)

cmd_parser = OptionParser(version="%prog 0.1")
cmd_parser.add_option("-p", "--pods", action="store_true", dest="pods", help="test pods")
cmd_parser.add_option("-d", "--deploys", action="store_true", dest="deploys", help="test deploys")
cmd_parser.add_option("-r", "--replicasets", action="store_true", dest="replicasets", help="test ReplicaSets")
cmd_parser.add_option("-a", "--daemonsets", action="store_true", dest="daemonsets", help="test DaemonSets")
cmd_parser.add_option("-n", "--nodes", action="store_true", dest="nodes", help="test nodes")
cmd_parser.add_option("-x", "--statefulsets", action="store_true", dest="statefulsets", help="test statefulsets")
cmd_parser.add_option("-t", "--replicationcontrollers", action="store_true", dest="replicationcontrollers", help="test replicationcontrollers")
cmd_parser.add_option("-c", "--context", action="store", dest="context", help="specify context", default="beta")
# cmd_parser.add_option("-n", "--namespace", action="store", dest="namespace", help="specify namespace: all,none", default="all")
(cmd_options, cmd_args) = cmd_parser.parse_args()

# if cmd_options.namespace != 'all':
namespace = "--all-namespaces"
# else:
#    namespace = ""


def comm(command_line):
    """Execute a command via subprocess."""
    """Return output of a system command."""
    process = subprocess.Popen(shlex.split(command_line), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, error = process.communicate()
    if error:
        matchobj = re.match(r'^No resources found.*', error)
        if matchobj:
            error = ''
    res = {'out': out, 'error': error}
    return {'out': out, 'error': error}


def runcom(tmpcom):
    """Simplify command and debug output."""
    logger.debug("tmpcom: %s" % tmpcom)
    x = comm(tmpcom)
    if x['error']:
        logger.error(x['error'])
        sys.exit(1)
    logger.debug(x['out'])
    return x['out']

def retres(tmpcom):
    """Filter output from kubectl."""
    x = runcom(tmpcom)
    output = []
    for i in x.split('\n'):
        if i:
            matchobj = re.match(r'^NAME.*', i)
            if not matchobj:
                output.append(i)
    return output

def procset(stype):
    tmpcom = "kubectl get %s %s" % (stype, namespace)
    x = retres(tmpcom)
    result = False
    msg = "ERRORS - "
    if x:
        for i in x:
            n = i.split()
            if n[2] != n[3]:
                msg += "%s:%s," % (n[0], n[1])
                result = True
    if result == False:
        mres = '%d %s: OK' % (len(x), stype)
    else:
        mres = '%d %s: %s' % (len(x), stype, msg[:-1])
    return { 'result': result, 'msg': mres }

def checkpods():
    """Check pods status."""
    result = False
    tmpcom = "kubectl get pods %s" % namespace
    x = retres(tmpcom)
    msg = "ERRORS - "
    if x:
        for i in x:
            n = i.split()[2]
            nt = n.split('/')
            if nt[0] != nt[1]:
                msg += "%s:%s:%s," % (i.split()[0], i.split()[1], i.split()[3])
                result = True
    if result == False:
        mres = '%d PODS: OK' % len(x)
    else:
        mres = '%d PODS: %s' % (len(x), msg[:-1])
    return { 'result': result, 'msg': mres }

def check_nodes():
    """Check node status."""
    result = False
    tmpcom = "kubectl get nodes"
    x = retres(tmpcom)
    msg = "NOT READY - "
    if x:
        for i in x:
            if i.split()[1] != "Ready":
                msg += "%s," % i.split()[0]
                result = True
    if result == False:
        mres = '%d NODES: OK' % len(x)
    else:
        mres = '%d NODES: %s' % (len(x), msg[:-1])
    return { 'result': result, 'msg': mres }

runcom('kubectl config use-context %s' % cmd_options.context)

if cmd_options.pods:
    x = checkpods()
elif cmd_options.deploys:
    x = procset('deployments')
elif cmd_options.replicasets:
    x = procset('replicasets')
elif cmd_options.daemonsets:
    x = procset('daemonsets')
elif cmd_options.nodes:
    x = check_nodes()
elif cmd_options.replicationcontrollers:
    x = procset('replicationcontrollers')
elif cmd_options.statefulsets:
    x = procset('statefulsets')
else:
    sys.exit("ERROR: please specify a test!")

if x['result']:
    print x['msg']
    sys.exit(1)
else:
    print x['msg']
    sys.exit(0)
