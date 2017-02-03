#!/opt/virtualenv/riemann-client/bin/python
from riemann_client.transport import TCPTransport
from riemann_client.client import QueuedClient
from optparse import OptionParser
import datetime
import shlex
import subprocess
import logging
import re
import sys
import datetime
from time import sleep

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# console logging
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
cformat = logging.Formatter('%(message)s')
# cformat = logging.Formatter('%(levelname)s: %(name)s - %(message)s')
ch.setFormatter(cformat)
logger.addHandler(ch)

namespace = "--all-namespaces"

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
    errcount = 0
    if x:
        for i in x:
            n = i.split()
            if n[2] != n[3]:
                errcount = errcount + 1
    return {'total': len(x), 'errors': errcount}

def checkpods():
    """Check pods status."""
    errcount = 0
    x = retres("kubectl get pods %s" % namespace)
    if x:
        for i in x:
            n = i.split()[2]
            nt = n.split('/')
            if nt[0] != nt[1]:
                errcount = errcount + 1
    return {'total': len(x), 'errors': errcount}

def check_nodes():
    """Check node status."""
    errcount = 0
    x = retres("kubectl get nodes")
    if x:
        for i in x:
            if i.split()[1] != "Ready":
                errcount = errcount + 1
    return {'total': len(x), 'errors': errcount}

while True:
    #with QueuedClient(TCPTransport("localhost", 5555), stay_connected=True) as client:
    with QueuedClient(TCPTransport("localhost", 5555)) as client:
        for context in ["beta", "prod"]:
            runcom('kubectl config use-context %s' % context)
            # pods
            x = checkpods()
            svcname = "kubemon-%s-pods-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-pods-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
            # deployments
            x = procset('deployments')
            svcname = "kubemon-%s-deployments-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-deployments-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
            # replicasets
            x = procset('replicasets')
            svcname = "kubemon-%s-replicasets-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-replicasets-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
            # daemonsets
            x = procset('daemonsets')
            svcname = "kubemon-%s-daemonsets-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-daemonsets-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
            # nodes
            x = check_nodes()
            svcname = "kubemon-%s-nodes-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-nodes-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
            # replicationcontrollers
            x = procset('replicationcontrollers')
            svcname = "kubemon-%s-replicationcontrollers-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-replicationcontrollers-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
            # statefulsets
            x = procset('statefulsets')
            svcname = "kubemon-%s-statefulsets-total" % context
            client.event(service=svcname, metric_f=x['total'])
            svcname = "kubemon-%s-statefulsets-errors" % context
            client.event(service=svcname, metric_f=x['errors'])
        # fuck it, ship it
        try:
            client.flush()
        except:
            print "%s ERROR: unable to excute flush!" % (datetime.datetime.today().strftime('%Y%m%d%H%M'))
        # and take a nap
        sleep(5)
