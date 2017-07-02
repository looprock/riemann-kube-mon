# riemann-kube-mon
Ship kubernetes status to riemann, logs to stdout as well as creates entries for unique events in redis so they can be retrieved from things like status pages or chatbots if needed.

# able to report on:

daemonsets

deployments

nodes

pods

replicasets

statefulsets

* replicationcontrollers - stubbed out since I cannot validate

# scripts

kube_monitor.py - report all the things
