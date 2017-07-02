#!/usr/bin/env python3
import pykube
import operator
from os.path import expanduser, exists
import json
import datetime
import redis
import time
from riemann_client.transport import TCPTransport
from riemann_client.client import QueuedClient
import sys
import socket
from time import sleep
import requests
import logging
import hashlib

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# we have no previous messages:
prevmsg = hashlib.sha256(b'no value is a good value')

# console logging
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
cformat = logging.Formatter('%(message)s')
# cformat = logging.Formatter('%(levelname)s: %(name)s - %(message)s')
ch.setFormatter(cformat)
logger.addHandler(ch)

home = expanduser("~")
kubeconfig = "%s/.kube/config" % home

riemannserver = '127.0.0.1'
redisserver = '127.0.0.1'
slack_url = 'https://hooks.slack.com/services/YEAHIDONTTHINKSO'
all_contexts = ["beta", "prod"]

r = redis.Redis(host=redisserver)

# wait for riemann to become available
riemanncheck = False
while not riemanncheck:
    sleep(2)
    logger.info("Trying to connect to Riemann...")
    try:
        with QueuedClient(TCPTransport(riemannserver, 5555)) as client:
            client.event(service="this-is-a-test")
            client.flush()
            riemanncheck = True
    except:
        pass

# wait for redis to become available
redischeck = False
while not redischeck:
    sleep(2)
    logger.info("Trying to connect to redis...")
    try:
        r.keys()
        redischeck = True
    except:
        pass

now = datetime.datetime.now().isoformat()
logger.info("%s Starting kube-monitor" % (now))

# event stream we can look at/poll from errbot, maybe some snapshot entry based on epoch or something..
# maybe push a key/value into redis and read it out from errbot ++ notification when one is created
# time to stand up the slack-gateway

class AutoVivification(dict):
    '''Implementation of perl's autovivification feature'''
    def __getitem__(self, item):
        try:
            return dict.__getitem__(self, item)
        except KeyError:
            value = self[item] = type(self)()
            return value

def get_all_namespaces():
    try:
        tmp = {}
        for kube_context in all_contexts:
            nslist = []
            pykube_config = pykube.KubeConfig.from_file(kubeconfig)
            pykube_config.set_current_context(kube_context)
            api = pykube.HTTPClient(pykube_config)
            namespaces = pykube.Namespace.objects(api)
            for ns in namespaces:
                nsobj = ns.obj
                if nsobj['status']['phase'] == "Active":
                    nslist.append(str(nsobj['metadata']['name']))
            tmp[kube_context] = nslist
        return tmp
    except (AttributeError, RuntimeError, socket.error, IOError) as e:
        now = datetime.datetime.now().isoformat()
        logger.error("%s ERROR: unable to collect information about namspaces for %s!" % (now, kube_context))
        logger.error(e)
        sys.exit(1)

def check_pods(api):
    result = AutoVivification()
    errcount = 0
    total = 0
    msg = ''
    ignore = ["ContainerCreating", "Terminating", "Succeeded"]
    # ignore = ["ContainerCreating", "Terminating"]
    for namespace in namespaces[kube_context]:
        pods = pykube.Pod.objects(api).filter(namespace=namespace)
        for pod in pods:
            kobj = pod.obj
            try:
                if kobj['status']['phase'] not in ignore:
                    total = total + 1
                    haserr = False
                    for i in kobj['status']['conditions']:
                        if str(i['status']) != 'True':
                            haserr = True
                            now = datetime.datetime.now().isoformat()
                            name = kobj['metadata']['name']
                            phase = kobj['status']['phase']
                            msg += "%s %s %s pod %s - phase: %s, type: %s: status: %s\n" % (now, kube_context, namespace, name, phase, i['type'], i['status'])
                    if haserr:
                        errcount = errcount + 1
            except:
                now = datetime.datetime.now().isoformat()
                logger.error("%s ERROR: unable to collect information about %s %s pod %s!" % (now, kube_context, namespace, kobj['metadata']['name']))
                pass
    result['total'] = total
    result['errors'] = errcount
    result['msg'] = msg
    return result

def check_nodes(api):
    msg = ''
    result = AutoVivification()
    errcount = 0
    total = 0
    nodes = pykube.Node.objects(api)
    for node in nodes:
        kobj = node.obj
        total = total + 1
        # print(json.dumps(kobj, indent=4))
        haserr = False
        try:
            for i in kobj['status']['conditions']:
                if i['type'] != "Ready":
                    if str(i['status']) != 'False':
                        haserr = True
                        now = datetime.datetime.now().isoformat()
                        name = kobj['metadata']['name']
                        phase = kobj['status']['phase']
                        msg += "%s %s node %s - phase: %s, type: %s: status: %s\n" % (now, kube_context, name, phase, i['type'], i['status'])
                else:
                    if str(i['status']) != 'True':
                        haserr = True
            if haserr:
                errcount = errcount + 1
        except:
            now = datetime.datetime.now().isoformat()
            logger.error("%s ERROR: unable to collect information about %s node %s!" % (now, kube_context, kobj['metadata']['name']))
            pass
    result['total'] = total
    result['errors'] = errcount
    result['msg'] = msg
    return result

def check_deploys(api):
    msg = ''
    result = AutoVivification()
    errcount = 0
    total = 0
    for namespace in namespaces[kube_context]:
        tmpobjects = pykube.Deployment.objects(api).filter(namespace=namespace)
        for tmpobject in tmpobjects:
            kobj = tmpobject.obj
            if kobj['spec']['replicas'] > 0:
                total = total + 1
                # print(json.dumps(kobj, indent=4))
                haserr = False
                try:
                    for i in kobj['status']['conditions']:
                        if i['type'] == 'Available':
                            if i['status'] != 'True':
                                haserr = True
                                now = datetime.datetime.now().isoformat()
                                name = kobj['metadata']['name']
                                msg += "%s %s %s deployment %s - type: %s: status: %s\n" % (now, kube_context, namespace, name, i['type'], i['status'])
                    if kobj['status']['availableReplicas'] != kobj['status']['replicas']:
                        haserr = True
                        now = datetime.datetime.now().isoformat()
                        name = kobj['metadata']['name']
                        availableReplicas = str(kobj['status']['availableReplicas'])
                        replicas = str(kobj['status']['replicas'])
                        msg += "%s %s %s deployment %s - replicas: %s: availableReplicas: %s\n" % (now, kube_context, namespace, name, replicas, availableReplicas)
                    if haserr:
                        errcount = errcount + 1
                except:
                    now = datetime.datetime.now().isoformat()
                    logger.error("%s ERROR: unable to collect information about %s %s deployment %s!" % (now, kube_context, namespace, kobj['metadata']['name']))
                    pass
    result['total'] = total
    result['errors'] = errcount
    result['msg'] = msg
    return result

def check_replicasets(api):
    msg = ''
    result = AutoVivification()
    errcount = 0
    total = 0
    for namespace in namespaces[kube_context]:
        tmpobjects = pykube.ReplicaSet.objects(api).filter(namespace=namespace)
        for tmpobject in tmpobjects:
            kobj = tmpobject.obj
            if kobj['spec']['replicas'] > 0:
                total = total + 1
                haserr = False
                # print(json.dumps(kobj, indent=4))
                # print("checking: %s %s" % (kube_context, kobj['metadata']['name']))
                try:
                    if kobj['status']['availableReplicas'] != kobj['status']['replicas']:
                        haserr = True
                        now = datetime.datetime.now().isoformat()
                        name = kobj['metadata']['name']
                        availableReplicas = str(kobj['status']['availableReplicas'])
                        replicas = str(kobj['status']['replicas'])
                        msg += "%s %s %s replicaset %s - replicas: %s: availableReplicas: %s\n" % (now, kube_context, namespace, name, replicas, availableReplicas)
                    if haserr:
                        errcount = errcount + 1
                except:
                    now = datetime.datetime.now().isoformat()
                    logger.error("%s ERROR: unable to collect information on %s %s replicaset %s" % (now, kube_context, namespace, kobj['metadata']['name']))
                    pass
    result['total'] = total
    result['errors'] = errcount
    result['msg'] = msg
    return result

def check_daemonsets(api):
    msg = ''
    result = AutoVivification()
    errcount = 0
    total = 0
    for namespace in namespaces[kube_context]:
        tmpobjects = pykube.DaemonSet.objects(api).filter(namespace=namespace)
        for tmpobject in tmpobjects:
            kobj = tmpobject.obj
            total = total + 1
            haserr = False
            try:
                # print(json.dumps(kobj, indent=4))
                currentNumberScheduled = kobj['status']['currentNumberScheduled']
                desiredNumberScheduled = kobj['status']['desiredNumberScheduled']
                numberReady = kobj['status']['numberReady']
                tmp = set([currentNumberScheduled, desiredNumberScheduled, numberReady])
                if len(tmp) > 1:
                    haserr = True
                    now = datetime.datetime.now().isoformat()
                    name = kobj['metadata']['name']
                    msg += "%s %s %s daemonset %s - currentNumberScheduled: %s: desiredNumberScheduled: %s, numberReady: %s\n" % (now, kube_context, namespace, name, str(currentNumberScheduled), str(desiredNumberScheduled), str(numberReady))
                if haserr:
                    errcount = errcount + 1
            except:
                now = datetime.datetime.now().isoformat()
                logger.error("%s ERROR: unable to collect information about %s %s daemonset %s!" % (now, kube_context, namespace, kobj['metadata']['name']))
                pass
    result['total'] = total
    result['errors'] = errcount
    result['msg'] = msg
    return result

# we don't have any so idk what constitutes a good or bad state
# ReplicationController
# def check_rcs(api):
#     msg = ''
#     result = AutoVivification()
#     errcount = 0
#     total = 0
#     for namespace in namespaces[kube_context]:
#         tmpobjects = pykube.ReplicationController.objects(api).filter(namespace=namespace)
#         for tmpobject in tmpobjects:
#             kobj = tmpobject.obj
#             total = total + 1
#             haserr = False
#             # print(json.dumps(kobj, indent=4))
#     result['total'] = total
#     result['errors'] = errcount
#     result['msg'] = msg
#     return result

# StatefulSet
def check_statefulsets(api):
    msg = ''
    result = AutoVivification()
    errcount = 0
    total = 0
    for namespace in namespaces[kube_context]:
        tmpobjects = pykube.StatefulSet.objects(api).filter(namespace=namespace)
        for tmpobject in tmpobjects:
            kobj = tmpobject.obj
            total = total + 1
            haserr = False
            try:
                # print(json.dumps(kobj, indent=4))
                if kobj['spec']['replicas'] != kobj['status']['replicas']:
                    haserr = True
                    now = datetime.datetime.now().isoformat()
                    name = kobj['metadata']['name']
                    msg += "%s %s %s statefulset %s - replicas spec: %s: replicas status: %s\n" % (now, kube_context, namespace, name, str(kobj['spec']['replicas']), str(kobj['status']['replicas']))
                if haserr:
                    errcount = errcount + 1
            except:
                now = datetime.datetime.now().isoformat()
                logger.error("%s ERROR: unable to collect information about %s %s statefulset %s!" % (now, kube_context, namespace, kobj['metadata']['name']))
                pass
    result['total'] = total
    result['errors'] = errcount
    result['msg'] = msg
    return result

def returnstate(errors):
    if errors > 0:
        state = "critical"
    else:
        state = "ok"
    return state

while True:
    with QueuedClient(TCPTransport(riemannserver, 5555)) as client:
        msg = ''
        data = AutoVivification()
        namespaces = get_all_namespaces()
        epoch_time = int(time.time())
        for kube_context in all_contexts:
            pykube_config = pykube.KubeConfig.from_file(kubeconfig)
            pykube_config.set_current_context(kube_context)
            api = pykube.HTTPClient(pykube_config)
            data['pods'][kube_context] = check_pods(api)
            data['nodes'][kube_context] = check_nodes(api)
            data['deployments'][kube_context] = check_deploys(api)
            data['replicasets'][kube_context] = check_replicasets(api)
            data['daemonsets'][kube_context] = check_daemonsets(api)
            # data['replicationcontrollers'][kube_context] = check_rcs(api)
            data['statefulsets'][kube_context] = check_statefulsets(api)
            for k in data.keys():
                x = data[k][kube_context]
                if 'msg' in list(x.keys()):
                    msg += x['msg']
                for ctype in ['total', 'errors']:
                    if ctype not in list(x.keys()):
                        logger.error("ERROR: %s %s missing value for %s!" % (kube_context, k, ctype))
                    else:
                        if kube_context == 'production':
                            svc_context = 'prod'
                        else:
                            svc_context = kube_context
                        svcname = "kubemon-%s-%s-%s" % (svc_context, k, ctype)
                        if ctype == "total":
                            client.event(service=svcname, metric_f=x[ctype])
                        if ctype == "errors":
                            client.event(service=svcname, metric_f=x[ctype], state=returnstate(x[ctype]))
        # print(json.dumps(data, indent=4))
        if msg:
            prevmsgdig = prevmsg.hexdigest()
            msghash = hashlib.sha256(b'msg')
            msgdig = msghash.hexdigest()
            # print("comparing msg: %s, to prevmsg: %s" % (msgdig, prevmsgdig))
            if msgdig != prevmsgdig:
                logger.error("%s ERROR: messages follow ->" % (datetime.datetime.now().isoformat()))
                logger.error(msg)
                # create a redis record that can be retrieved by our chatops bot for more information
                r.set(epoch_time, msg, ex=604800)
                slack_string = 'kube-monitor alert triggered. For more information, msg @ops with "!kubemon %s"' % epoch_time
                data = {'text': slack_string}
                inform = requests.post(slack_url, data=json.dumps(data))
                prevmsg = hashlib.sha256(b'msg')
        try:
            client.flush()
        except (AttributeError, RuntimeError, socket.error, IOError) as e:
            logger.error("%s ERROR: unable to excute flush!" % (datetime.datetime.now().isoformat()))
            logger.error(e)
            sys.exit()
    # and take a nap
    sleep(5)
