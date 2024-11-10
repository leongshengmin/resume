Elasticsearch uses it's own ZenDiscovery module (similar to RAFT) for node discovery, leader election without relying on external components e.g. Zookeeper.

Kafka, Clickhouse both use Zookeeper for leader election, node discovery respectively. Zookeeper uses ZAP (similar to PAXOS) for consistency.

### 1. ES Node Discovery
Each node on bootstrap will connect to the seed list (master-eligible nodes) to discover other nodes in the cluster.
This creates a fully connected graph between each node, wherein each node can see other nodes in the cluster.
```
conf/elasticsearch.yml:
    # hosts should be master-eligible nodes
    discovery.zen.ping.unicast.hosts: [1.1.1.1, 1.1.1.2, 1.1.1.3]
```

### 2. ES Master Election
To avoid split-brain, a quorum of master-eligible nodes should be running.
##### 2.1 When is a Master Election initiated?
Master election is initiated by a master-eligible node when all these conditions are TRUE:
1. the current master-eligible node is not master
2. master-eligible node queries other known cluster nodes using `ZenDiscovery` ping operation and sees no nodes connected to the master.
3. quorum of master-eligible nodes (including this node) not connected to master
##### 2.2 What decides who should be Master during Master Elections?
1. Master-eligible nodes with the latest `ClusterStateVersion` will take priority. I.e. to avoid loss of committed cluster state changes
2. Out of the master-eligible nodes with the latest `ClusterStateVersion`, the node with the lowest node ID will be picked. (so that elected candidate will be stable)
##### 2.3 What happens in a successful election?
2 scenarios -- node A selects another node / itself as master. Both require a quorum of votes to be accepted which prevents split-brain.
**Case 1: If master-eligible node A chooses B to be master.**
1. Node A sends a join request to Node B (to join the new cluster):
	1. If node B picks itself as master, it takes this join request from A as a vote. Once B has collected a quorum of votes from master-eligible nodes, it becomes master. Node A completes the join (and joins the new cluster) when a new cluster state is published for A.
	2. If B becomes master, B adds A to the cluster and publishes the latest cluster state (includes information of A).
	3. If B picks some other node as master, it rejects this join request and node A will initiate the next election.
**Case 2: node A selects itself as master**
1. Node A waits for other nodes to join (ie. wait for votes from other master-eligible nodes). Once quorum of votes collected, it considers itself master and sends a cluster state update to the cluster.
```
// https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L443-L465
if (transportService.getLocalNode().equals(masterNode)) {
	final int requiredJoins = Math.max(0, electMaster.minimumMasterNodes() - 1); // we count as one
	logger.debug("elected as master, waiting for incoming joins ([{}] needed)", requiredJoins);
	nodeJoinController.waitToBeElectedAsMaster(requiredJoins, masterElectionWaitForJoinsTimeout,
			new NodeJoinController.ElectionCallback() {
				@Override
				public void onElectedAsMaster(ClusterState state) {
					synchronized (stateMutex) {
						joinThreadControl.markThreadAsDone(currentThread);
					}
				}

				@Override
				public void onFailure(Throwable t) {
					logger.trace("failed while waiting for nodes to join, rejoining", t);
					synchronized (stateMutex) {
						joinThreadControl.markThreadAsDoneAndStartNew(currentThread);
					}
				}
			}

	);
}
```
### 3. ES Node Error Detection (Healthcheck)
#### 3.1 Fault Detection (Master + Nodes)
The fault detection can be described as a heartbeat-like mechanism. There are two types of fault detection:
1. master to regularly detect the other nodes in the cluster
2. other nodes in the cluster to regularly detect the cluster's current master. 
The detection method performs regular ping requests.

**3.1.1. Master -> Node**
If the master detects that a node is not connected, the removeNode operation is performed to remove the node from the cluster_state, and a new cluster_state is published. When a new cluster_state is applied to each module, a number of recovery operations are performed, for example, to select a new primaryShard or replica, or to perform data replication.

```
// https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L556-L587

private void removeNode(final DiscoveryNode node, final String source, final String reason) {
	masterService.submitStateUpdateTask(
			source + "(" + node + "), reason(" + reason + ")",
			new NodeRemovalClusterStateTaskExecutor.Task(node, reason),
			ClusterStateTaskConfig.build(Priority.IMMEDIATE),
			nodeRemovalExecutor,
			nodeRemovalExecutor);
}

private void handleLeaveRequest(final DiscoveryNode node) {
	if (lifecycleState() != Lifecycle.State.STARTED) {
		// not started, ignore a node failure
		return;
	}
	if (localNodeMaster()) {
		removeNode(node, "zen-disco-node-left", "left");
	} else if (node.equals(clusterState().nodes().getMasterNode())) {
		handleMasterGone(node, null, "shut_down");
	}
}

private void handleNodeFailure(final DiscoveryNode node, final String reason) {
	if (lifecycleState() != Lifecycle.State.STARTED) {
		// not started, ignore a node failure
		return;
	}
	if (!localNodeMaster()) {
		// nothing to do here...
		return;
	}
	removeNode(node, "zen-disco-node-failed", reason);
}
```

**3.1.2. Node -> Master**
If a node detects that the master is not connected, the pending cluster_state which has not yet been committed to memory is cleared, and a rejoin is initiated to rejoin the cluster (a new master election is triggered if the election conditions are met).

```
https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L609-L628

private void handleMasterGone(final DiscoveryNode masterNode, final Throwable cause, final String reason) {
	if (lifecycleState() != Lifecycle.State.STARTED) {
		// not started, ignore a master failure
		return;
	}
	if (localNodeMaster()) {
		// we might get this on both a master telling us shutting down, and then the disconnect failure
		return;
	}

	logger.info(() -> new ParameterizedMessage("master_left [{}], reason [{}]", masterNode, reason), cause);

	synchronized (stateMutex) {
		if (localNodeMaster() == false && masterNode.equals(committedState.get().nodes().getMasterNode())) {
			// flush any pending cluster states from old master, so it will not be set as master again
			pendingStatesQueue.failAllStatesAndClear(new ElasticsearchException("master left [{}]", reason));
			rejoin("master left (reason = " + reason + ")");
		}
	}
}
```

#### 3.2 When does a rejoin operation for Master nodes happen?
Rejoin can be called if:
1. number of discovered master nodes < minimumMasterNodes; or
2. multiple masters are discovered

**3.2.1. Master node count < minimumMasterNodes**

When master doesn't meet the quorum condition, it needs to exit from master status and rejoin cluster since if number of discovered masters < quorum then the number of followers will clearly be < quorum (plus any publish will fail due to lack of ACK).

electMasterService determines if this quorum condition is met when the number of discovered master nodes > minimumMasterNodes.
```
https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ElectMasterService.java#L153-L156

public boolean hasEnoughMasterNodes(Iterable<DiscoveryNode> nodes) {
	final int count = countMasterNodes(nodes);
	return count > 0 && (minimumMasterNodes < 0 || count >= minimumMasterNodes);
}

https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ElectMasterService.java#L115-L123
public int countMasterNodes(Iterable<DiscoveryNode> nodes) {
	int count = 0;
	for (DiscoveryNode node : nodes) {
		if (node.isMasterNode()) {
			count++;
		}
	}
	return count;
}

// https://github.com/elastic/elasticsearch/blob/main/server/src/main/java/org/elasticsearch/cluster/node/DiscoveryNode.java#L422-L427
/**
 * Can this node become master or not.
 */
public boolean isMasterNode() {
	return roles.contains(DiscoveryNodeRole.MASTER_ROLE);
}
```

In the `removeNode` operation, the `nodeRemovalExecutor` (an instance of the `ZenNodeRemovalClusterStateTaskExecutor` class), will first verify if there is a quorum of master-eligible nodes discovered (to ACK change in cluster state). If not, rejoin is performed.

```
https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L556-L563

private void removeNode(final DiscoveryNode node, final String source, final String reason) {
	masterService.submitStateUpdateTask(
			source + "(" + node + "), reason(" + reason + ")",
			new NodeRemovalClusterStateTaskExecutor.Task(node, reason),
			ClusterStateTaskConfig.build(Priority.IMMEDIATE),
			nodeRemovalExecutor,
			nodeRemovalExecutor);
}

// functions that call removeNode
private void handleLeaveRequest(final DiscoveryNode node) {
	if (lifecycleState() != Lifecycle.State.STARTED) {
		// not started, ignore a node failure
		return;
	}
	if (localNodeMaster()) {
		removeNode(node, "zen-disco-node-left", "left");
	} else if (node.equals(clusterState().nodes().getMasterNode())) {
		handleMasterGone(node, null, "shut_down");
	}
}

private void handleNodeFailure(final DiscoveryNode node, final String reason) {
	if (lifecycleState() != Lifecycle.State.STARTED) {
		// not started, ignore a node failure
		return;
	}
	if (!localNodeMaster()) {
		// nothing to do here...
		return;
	}
	removeNode(node, "zen-disco-node-failed", reason);
}

// https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L609-L1241

static class ZenNodeRemovalClusterStateTaskExecutor extends NodeRemovalClusterStateTaskExecutor {
...

	@Override
	protected ClusterTasksResult<Task> getTaskClusterTasksResult(ClusterState currentState, List<Task> tasks, ClusterState remainingNodesClusterState) {
		if (electMasterService.hasEnoughMasterNodes(remainingNodesClusterState.nodes()) == false) {
			final ClusterTasksResult.Builder<Task> resultBuilder = ClusterTasksResult.<Task>builder().successes(tasks);
			final int masterNodes = electMasterService.countMasterNodes(remainingNodesClusterState.nodes());
			rejoin.accept(LoggerMessageFormat.format("not enough master nodes (has [{}], but needed [{}])",
				masterNodes, electMasterService.minimumMasterNodes()));
			return resultBuilder.build(currentState);
		} else {
			return super.getTaskClusterTasksResult(currentState, tasks, remainingNodesClusterState);
		}
	}
}
```

**3.2.2. When there are multiple master nodes discovered in Ping**
**Handling multiple master nodes in Ping Operation**
During periodic pings to other nodes, we can discover that another node is also master. In this case, the cluster_state version of this node is compared with the other master node. The node with the latest version becomes master, and the node with an earlier version performs rejoin.
```
// https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L1042

private class NodeFaultDetectionListener extends NodesFaultDetection.Listener {

	private final AtomicInteger pingsWhileMaster = new AtomicInteger(0);

	@Override
	public void onNodeFailure(DiscoveryNode node, String reason) {
		handleNodeFailure(node, reason);
	}

	@Override
	public void onPingReceived(final NodesFaultDetection.PingRequest pingRequest) {
		// if we are master, we don't expect any fault detection from another node. If we get it
		// means we potentially have two masters in the cluster.
		if (!localNodeMaster()) {
			pingsWhileMaster.set(0);
			return;
		}

		if (pingsWhileMaster.incrementAndGet() < maxPingsFromAnotherMaster) {
			logger.trace("got a ping from another master {}. current ping count: [{}]", pingRequest.masterNode(),
				pingsWhileMaster.get());
			return;
		}
		logger.debug("got a ping from another master {}. resolving who should rejoin. current ping count: [{}]",
			pingRequest.masterNode(), pingsWhileMaster.get());
		synchronized (stateMutex) {
			ClusterState currentState = committedState.get();
			if (currentState.nodes().isLocalNodeElectedMaster()) {
				pingsWhileMaster.set(0);
				handleAnotherMaster(currentState, pingRequest.masterNode(), pingRequest.clusterStateVersion(), "node fd ping");
			}
		}
	}
}

// https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L921

private void handleAnotherMaster(ClusterState localClusterState, final DiscoveryNode otherMaster, long otherClusterStateVersion, String reason) {
	assert localClusterState.nodes().isLocalNodeElectedMaster() : "handleAnotherMaster called but current node is not a master";
	assert Thread.holdsLock(stateMutex);

	if (otherClusterStateVersion > localClusterState.version()) {
		rejoin("zen-disco-discovered another master with a new cluster_state [" + otherMaster + "][" + reason + "]");
	} else {
		// TODO: do this outside mutex
		logger.warn("discovered [{}] which is also master but with an older cluster_state, telling [{}] to rejoin the cluster ([{}])",
			otherMaster, otherMaster, reason);
		try {
			// make sure we're connected to this node (connect to node does nothing if we're already connected)
			// since the network connections are asymmetric, it may be that we received a state but have disconnected from the node
			// in the past (after a master failure, for example)
			transportService.connectToNode(otherMaster);
			transportService.sendRequest(otherMaster, DISCOVERY_REJOIN_ACTION_NAME,
				new RejoinClusterRequest(localClusterState.nodes().getLocalNodeId()),
				new EmptyTransportResponseHandler(ThreadPool.Names.SAME) {

				@Override
				public void handleException(TransportException exp) {
					logger.warn(() -> new ParameterizedMessage("failed to send rejoin request to [{}]", otherMaster), exp);
				}
			});
		} catch (Exception e) {
			logger.warn(() -> new ParameterizedMessage("failed to send rejoin request to [{}]", otherMaster), e);
		}
	}
}
```

#### 3.3. Atomicity guarantee for ClusterState changes made by different threads within the master process

First, atomicity must be guaranteed when different threads change ClusterState within the master process. Imagine that two threads are modifying the ClusterState, and they are making their own changes. Without concurrent protection, modifications committed by the last thread commit overwrite the modifications committed by the first thread or result in an invalid state change.

To resolve this issue, ES commits a Task to MasterService whenever a ClusterState update is required, so that MasterService only uses one thread to sequentially handle the Tasks. The current ClusterState is used as the parameter of the execute function of the Task when it is being handled. This way, it guarantees that all Tasks are changed based on the currentClusterState, and sequential execution for different Tasks is guaranteed.
https://www.alibabacloud.com/blog/elasticsearch-distributed-consistency-principles-analysis-2---meta_594359
#### 3.4 Two Phase Commit for Cluster State Changes
Publishing the new cluster_state is divided into the **send** phase and the **commit** phase. The send phase requires the quorum to ACK the published cluster state before commit. If a less than a quorum of the master nodes return an ACK, this may be due to a new elected master or that quorum of the master nodes are not connected, in this case the master needs to perform a rejoin.

[![2 phase commit](https://yqintl.alicdn.com/c27d6774d4123ea338713d9c3824018a5182639b.png)](https://yqintl.alicdn.com/c27d6774d4123ea338713d9c3824018a5182639b.png)
https://www.alibabacloud.com/blog/elasticsearch-distributed-consistency-principles-analysis-2---meta_594359

**Why 2 Phase Commit is Required?**

The Two-Phase Commit (2PC) protocol is a distributed algorithm designed to ensure strong data consistency across multiple nodes in a system. It guarantees that a transaction either succeeds entirely on all nodes (commit), or fails entirely on all nodes (rollback).

*Example scenario:*
1. Node A originally the master node but due to a network partition, current master node loses followers, causing Node B to become the new master node.
2. Node A still thinks that it is the current master node and publishes a new cluster state (e.g. to remove nodes that it thinks are no longer in the cluster).
	1. Without 2 Phase Commit, cluster state publish by Node A will be successful when it should not have been.
	2. With 2 Phase Commit, cluster state publish will not be ACKed.
		1. Since node B being master means quorum of master nodes consider B to be master and will reject publish made by A.
		2. Node A will observe that publish failed and clear pending cluster state changes +  rejoin cluster to find the actual master.

> A master node in Elasticsearch continuously [monitors the cluster nodes](https://www.elastic.co/guide/en/elasticsearch/reference/current/cluster-fault-detection.html) and removes any node from the cluster that doesn’t respond to its pings in a timely fashion. If the master is left with too few nodes, it will step down and a new master election will start.
> 
   When a network partition causes a master node to lose many followers, there is a short window in time until the node loss is detected and the master steps down. During that window, the master may erroneously accept and acknowledge cluster state changes. To avoid this, we introduce a new phase to cluster state publishing where the proposed cluster state is sent to all nodes but is not yet committed. Only once enough nodes actively acknowledge the change, it is committed and commit messages are sent to the nodes. See [#13062](https://github.com/elastic/elasticsearch/issues/13062).
   https://github.com/elastic/elasticsearch/blob/main/docs/resiliency/index.asciidoc#use-two-phase-commit-for-cluster-state-publishing-status-done-v500

```
// https://github.com/elastic/elasticsearch/blob/v7.10.0/server/src/main/java/org/elasticsearch/discovery/zen/ZenDiscovery.java#L320-L390
        
 @Override
public void publish(ClusterChangedEvent clusterChangedEvent, ActionListener<Void> publishListener, AckListener ackListener) {
	ClusterState newState = clusterChangedEvent.state();
	assert newState.getNodes().isLocalNodeElectedMaster() : "Shouldn't publish state when not master " + clusterChangedEvent.source();

	try {

		// state got changed locally (maybe because another master published to us)
		if (clusterChangedEvent.previousState() != this.committedState.get()) {
			throw new FailedToCommitClusterStateException("state was mutated while calculating new CS update");
		}

		pendingStatesQueue.addPending(newState);

		publishClusterState.publish(clusterChangedEvent, electMaster.minimumMasterNodes(), ackListener);
	} catch (FailedToCommitClusterStateException t) {
		// cluster service logs a WARN message
		logger.debug("failed to publish cluster state version [{}] (not enough nodes acknowledged, min master nodes [{}])",
			newState.version(), electMaster.minimumMasterNodes());

		synchronized (stateMutex) {
			pendingStatesQueue.failAllStatesAndClear(
				new ElasticsearchException("failed to publish cluster state"));

			rejoin("zen-disco-failed-to-publish");
		}

		publishListener.onFailure(t);
		return;
	}

	final DiscoveryNode localNode = newState.getNodes().getLocalNode();
	final AtomicBoolean processedOrFailed = new AtomicBoolean();
	pendingStatesQueue.markAsCommitted(newState.stateUUID(),
		new PendingClusterStatesQueue.StateProcessedListener() {
			@Override
			public void onNewClusterStateProcessed() {
				processedOrFailed.set(true);
				publishListener.onResponse(null);
				ackListener.onNodeAck(localNode, null);
			}

			@Override
			public void onNewClusterStateFailed(Exception e) {
				processedOrFailed.set(true);
				publishListener.onFailure(e);
				ackListener.onNodeAck(localNode, e);
				logger.warn(() -> new ParameterizedMessage(
						"failed while applying cluster state locally [{}]", clusterChangedEvent.source()), e);
			}
		});

	synchronized (stateMutex) {
		if (clusterChangedEvent.previousState() != this.committedState.get()) {
			publishListener.onFailure(
					new FailedToCommitClusterStateException("local state was mutated while CS update was published to other nodes")
			);
			return;
		}

		boolean sentToApplier = processNextCommittedClusterState("master " + newState.nodes().getMasterNode() +
			" committed version [" + newState.version() + "] source [" + clusterChangedEvent.source() + "]");
		if (sentToApplier == false && processedOrFailed.get() == false) {
			assert false : "cluster state published locally neither processed nor failed: " + newState;
			logger.warn("cluster state with version [{}] that is published locally has neither been processed nor failed",
				newState.version());
			publishListener.onFailure(new FailedToCommitClusterStateException("cluster state that is published locally has neither " +
					"been processed nor failed"));
		}
	}
}

```

### 4. ES Metadata
https://www.alibabacloud.com/blog/elasticsearch-distributed-consistency-principles-analysis-2---meta%5C_594359?spm=a2c65.11461447.0.0.460e1107c5kGpY

**ClusterState**
Each node in the cluster maintains a current ClusterState in **memory**, which indicates various states within the current cluster. These information are kept in memory since they may change over time (e.g. `version`, `stateUUID`).

ClusterState contains the following information:
```
long version: current version number, which increments by 1 for every update
String stateUUID: the unique id corresponding to the state
RoutingTable routingTable: routing table for all indexes
DiscoveryNodes nodes: current cluster nodes
MetaData metaData: meta data of the cluster
ClusterBlocks blocks: used to block some operations
ImmutableOpenMap<String, Custom> customs: custom configuration
ClusterName clusterName: cluster name
```

**Cluster MetaData**
Each node also contains the following cluster metadata that is persisted on disk (rather than in memory). The clusterUUID is used to identify which cluster a node belongs to.

```
String clusterUUID: the unique id of the cluster.
long version: current version number, which increments by 1 for every update
Settings persistentSettings: persistent cluster settings
ImmutableOpenMap<String, IndexMetaData> indices: Meta of all Indexes
ImmutableOpenMap<String, IndexTemplateMetaData> templates: Meta of all templates
ImmutableOpenMap<String, Custom> customs: custom configuration
```

**Index MetaData**
```
long version: current version number, which increments by 1 for every update.
int routingNumShards: used for routing shard count; it can only be the multiples of numberOfShards of this Index, which is used for split.
State state: Index status, and it is an enum with the values  OPEN or CLOSE.
Settings settings: configurations, such as numbersOfShards and numbersOfRepilicas.
ImmutableOpenMap<String, MappingMetaData> mappings: mapping of the Index
ImmutableOpenMap<String, Custom> customs: custom configuration.
ImmutableOpenMap<String, AliasMetaData> aliases: alias
long[] primaryTerms: primaryTerm increments by 1 whenever a Shard switches the Primary, used to maintain the order.
ImmutableOpenIntMap<Set<String>> inSyncAllocationIds: represents the AllocationId at InSync state, and it is used to ensure data consistency, which is described in later articles.
```

#### 4.1. What is stored in the Data directory of an ES node

First, when an ES node is started, a data directory is configured, which is similar to the following. This node only has the Index of a single Shard.

```
$tree
.
`-- nodes
    `-- 0
        |-- _state
        |   |-- global-1.st
        |   `-- node-0.st
        |-- indices
        |   `-- 2Scrm6nuQOOxUN2ewtrNJw
        |       |-- 0
        |       |   |-- _state
        |       |   |   `-- state-0.st
        |       |   |-- index
        |       |   |   |-- segments_1
        |       |   |   `-- write.lock
        |       |   `-- translog
        |       |       |-- translog-1.tlog
        |       |       `-- translog.ckp
        |       `-- _state
        |           `-- state-2.st
        `-- node.lock
```

**nodes/0/_state/**

This directory is at the node level. The global-1.st file under this directory stores the contents mentioned above in MetaData, except for the IndexMetaData part, which includes some configurations and templates at the cluster level. node-0.st stores the NodeId.

**nodes/0/indices/2Scrm6nuQOOxUN2ewtrNJw/_state/**

This directory is at the index level, 2Scrm6nuQOOxUN2ewtrNJw is IndexId, and the state-2.st file under this directory stores the IndexMetaData mentioned above.

**nodes/0/indices/2Scrm6nuQOOxUN2ewtrNJw/0/_state/**

This directory is at the shard level, and state-0.st under this directory stores ShardStateMetaData, which contains information such as allocationId and whether it is primary. ShardStateMetaData is managed in the IndexShard module, which is not that relevant to other Meta, so we will not discuss details here.

As you see, the cluster-related MetaData and the Index MetaData are stored in different directories. In addition, the cluster-related Meta is stored on all MasterNodes and DataNodes, while the Index Meta is stored on all MasterNodes and the DataNodes that already store this Index data.

Cluster MetaData is persisted on all nodes and so can be used for cluster recovery.

#### 4.2 Recovering an ES Cluster (Quorum of master nodes are down)

If quorum of the master nodes are stopped, we can still recover the cluster by starting up the nodes again as long as the cluster metadata is still present on disk.

However, if quorum of the master nodes are no longer present, we can perform [unsafe cluster bootstrapping](https://www.elastic.co/guide/en/elasticsearch/reference/current/node-tool.html#node-tool-unsafe-bootstrap) `elasticsearch-node unsafe-bootstrap` which will override the cluster's voting configuration and use the local master node's cluster metadata to form a new cluster.
- cluster state is loaded from target master node's disk
- voting configuration (which is the set of master-eligible nodes that can vote to elect a new master / commit a new cluster state) is reset to just include the target node.
- clusterUUID is reset to `Metadata.UNKNOWN_CLUSTER_UUID` and so we would need an additional step to move nodes from the failed cluster to the new cluster with the new cluster UUID
- persist and commit reset cluster state
Would also need to run `elasticsearch-node detach-cluster` on the failed cluster nodes to migrate them to use the new clusterUUID (by resetting the clusterUUID persisted on the detached node).
```
// https://github.com/elastic/elasticsearch/blob/main/server/src/main/java/org/elasticsearch/cluster/coordination/UnsafeBootstrapMasterCommand.java#L102

protected void processDataPaths(Terminal terminal, Path[] dataPaths, OptionSet options, Environment env) throws IOException {
	final PersistedClusterStateService persistedClusterStateService = createPersistedClusterStateService(env.settings(), dataPaths); <---------------------- load cluster state from disk

	final Tuple<Long, ClusterState> state = loadTermAndClusterState(persistedClusterStateService, env);
	final ClusterState oldClusterState = state.v2();

	final Metadata metadata = oldClusterState.metadata();

	final CoordinationMetadata coordinationMetadata = metadata.coordinationMetadata();
	if (coordinationMetadata == null
		|| coordinationMetadata.getLastCommittedConfiguration() == null
		|| coordinationMetadata.getLastCommittedConfiguration().isEmpty()) {
		throw new ElasticsearchException(EMPTY_LAST_COMMITTED_VOTING_CONFIG_MSG);
	}
	terminal.println(
		String.format(Locale.ROOT, CLUSTER_STATE_TERM_VERSION_MSG_FORMAT, coordinationMetadata.term(), metadata.version())
	);

	CoordinationMetadata newCoordinationMetadata = CoordinationMetadata.builder(coordinationMetadata)
		.clearVotingConfigExclusions()
		.lastAcceptedConfiguration(
			new CoordinationMetadata.VotingConfiguration(Collections.singleton(persistedClusterStateService.getNodeId()))
		)
		.lastCommittedConfiguration(
			new CoordinationMetadata.VotingConfiguration(Collections.singleton(persistedClusterStateService.getNodeId())) <---------------------- reset voting config to just this node
		)
		.build();

	Settings persistentSettings = Settings.builder().put(metadata.persistentSettings()).put(UNSAFE_BOOTSTRAP.getKey(), true).build();
	Metadata.Builder newMetadata = Metadata.builder(metadata)
		.clusterUUID(Metadata.UNKNOWN_CLUSTER_UUID) <---------------------- reset cluster uuid to form a new cluster
		.generateClusterUuidIfNeeded()
		.clusterUUIDCommitted(true)
		.persistentSettings(persistentSettings)
		.coordinationMetadata(newCoordinationMetadata);
	for (IndexMetadata indexMetadata : metadata.indices().values()) {
		newMetadata.put(
			IndexMetadata.builder(indexMetadata)
				.settings(
					Settings.builder()
						.put(indexMetadata.getSettings())
						.put(IndexMetadata.SETTING_HISTORY_UUID, UUIDs.randomBase64UUID())
				)
		);
	}

	final ClusterState newClusterState = ClusterState.builder(oldClusterState).metadata(newMetadata).build();

	if (terminal.isPrintable(Terminal.Verbosity.VERBOSE)) {
		terminal.println(
			Terminal.Verbosity.VERBOSE,
			"[old cluster state = " + oldClusterState + ", new cluster state = " + newClusterState + "]"
		);
	}

	confirm(terminal, CONFIRMATION_MSG);

	try (PersistedClusterStateService.Writer writer = persistedClusterStateService.createWriter()) {
		writer.writeFullStateAndCommit(state.v1(), newClusterState); <---------------------- persist new cluster state
	}

	terminal.println(MASTER_NODE_BOOTSTRAPPED_MSG);
}
```
[repurpose](https://www.elastic.co/guide/en/elasticsearch/reference/current/node-tool.html#node-tool-repurpose) a data node into a master node if a quorum of master nodes are hard down won't work since node join operation also requires cluster state publish to be successful (but that will not work since quorum of the masters are already lost).

When the Master process decides to recover the Meta, it sends the request to MasterNode and DataNode to obtain the MetaData on its machine. For a cluster, the Meta with the latest version number is selected. Likewise, for each Index, the Meta with the latest version number is selected. The Meta of the cluster and each Index then combine to form the latest Meta.

### 5. ES Data Ingestion Consistency
https://www.alibabacloud.com/blog/elasticsearch-distributed-consistency-principles-analysis-3---data_594360
#### 5.1 Write Process (ACKS / ISRs)
ES write process involves writing data to the Primary node first, then concurrently writing it to Replica nodes and finally returning it to the Client. The process is as follows:

Check the Active Shard count.
```
String activeShardCountFailure = checkActiveShardCount();
```
Write to the Primary.
```
primaryResult = primary.perform(request);
```
Concurrently initiate write requests to all replicas.
```
performOnReplicas(replicaRequest, globalCheckpoint, replicationGroup.getRoutingTable());
```
After all replicas are returned or fail, they are returned to the Client.

**1. Why must the Active Shard count be checked in the first step?**

(Similar to acks in kafka but this is the # of nodes that should ACK the write request)
There is a parameter called wait_for_active_shards in ES. It is an Index setting and can be attached to the request. This parameter indicates the minimum numbers of Active copies that the Shard should have before each write operation. Assume that we have an Index in which each Shard has three Replica nodes, totaling four copies (plus Primary node). If wait_for_active_shards is configured to 3, a maximum of one Replica node is allowed to crash; if two Replica nodes crash, the number Active copies is less than three and, at that point, the write operation is not allowed.

This parameter is set to 1 by default, which means that the write operation is allowed if the Primary node exists, meaning this parameter is not use at this point. If it is set to a number greater than 1, it can have a protective effect, ensuring that the written data has higher reliability. However, this parameter only carries out the check before the write operation, which cannot guarantee that the data is written successfully to the copies; thus, the minimum number of copies to which the data is written is not strictly guaranteed.

**2. After writing to the Primary node finishes, why is it not returned until all Replica nodes respond (or the connection fails)?**

In earlier versions of ES, asynchronous replication was allowed between the Primary node and Replica nodes, which meant that the Primary node returned once writing was successful. But, in this mode, if the Primary node crashes, there is a risk of data loss, and it is difficult to guarantee that the data read from Replica nodes is up to date. So, ES stopped using asynchronous mode. Now, the Primary node is not returned to the Client until the Replica nodes are returned.

Because the Primary node is not returned to the Client until all Replica nodes are returned, the latency is affected by the slowest Replica node, which is a clear disadvantage of the current ES architecture.

> opensearch segment replication tackles the indexing latency issue by using lower availability guarantees -- ACK is only performed by the node hosting primary shard after write request succeeded (ie local write to translog + local Lucene write). Replication is on the segment level which happens async to nodes hosting replica shards.

**3. If writing to a Replica node continuously fails, do user lookups see legacy data?**

> tldr; ES maintains something like an ISR In kafka wherein the ISR comprises of the set of primary + replica shards that have in sync (ie. no write request failures) and therefore can serve read requests.

In other words, assuming writing to a Replica node continuously fails, the data in the Replica node could be much older than that in the Primary node. We know that, in ES, Replicas can also handle read requests, so does the user read the legacy data in this Replica node?

The answer is that, **if writing to a Replica node fails, the Primary node reports the issue to the Master, and the Master then updates the InSyncAllocations configuration of the Index in Meta and removes the Replica node. After that, it no longer handles read requests.** Users can still read the data on this Replica node before Meta update reaches every Node, but this does not happen after Meta update completes. This solution is not strict.
Maintaining InSyncAllocation in ES uses the PacificA algorithm.

#### 5.2 Write Process (Translog)

From the perspective of Primary shard, a write request is written to Lucene before it is written to translog.

**1. Why is translog write required?**

Translog is similar to commitlog in a database, or binlog. Once translog write is successful and flushed, the data is flushed directly to the disk, which guarantees data security, so that Segment can be flushed to the disk later. Because translog is written using append, write performance is better than using random write.

In addition, because translog records every data change and the order in which the data changes, it can be used for data recovery. Data recovery consists of two parts: First, after the node reboots, the Segment data that has not been flushed to the disk before reboot is recovered from translog; second, it is used for data synchronization between the Primary node and the new Replica node, which is the process by which the Replica tries to keep up with the Primary data.

**2. Why is Lucene write required before translog write?**

Lucene write writes the data to memory. After the write operation is finished, the data can be read immediately on refresh; translog write flushes data to the disk for data persistence and recovery. Normally, in distributed systems, commitLog is written for data persistence first, then this change is applied to the memory. So, why does ES work in exactly the opposite way? It is likely that the main reason is that, when writing to Lucene, Lucene runs various data checks, and the Lucene write operation may fail. If translog is written first, you may have to deal with the issue of Lucene write continuously failing while the translog write operation is successful. So, ES adopted the process of writing to Lucene first.

#### 5.3 How is PacificA Algorithm used in ES' data replication model (for determining leader of ISR ie. primary shard)

The Elasticsearch data replication model is based on the primary-backup model and is described very well in the PacificA paper of Microsoft Research. That model is based on having a single copy from the replication group that acts as the primary shard. The other copies are called replica shards. The primary serves as the main entry point for all indexing operations. It is in charge of validating them and making sure they are correct. Once an index operation has been accepted by the primary, the primary is also responsible for replicating the operation to the other copies.

The algorithm has the following features:  

1. Has strong consistency.
2. Synchronizes the data from a single Primary node with multiple Secondary nodes.
3. Uses additional consistency components for Configuration maintenance.
4. Supports writes even when a minority of Replica nodes are available.

The ES design refers to the PacificA algorithm. It maintains Index Meta through the Master, which is similar to Configuration maintenance by the Configuration Manager, as discussed in the paper. In IndexMeta, InSyncAllocationIds represents the currently available Shards, which is similar to Replica Group maintenance in the paper. Next, we introduce the SequenceNumber and Checkpoint in ES. These two classes are similar to the Serial Number and Committed Point in the PacificA algorithm.
##### Pacifica Algorithm - Glossary Terms

1. Replica Group: A dataset in which each piece of data is a copy of another, and each copy is a Replica node. Only one copy in a Replica Group is the Primary node; the rest are Secondary nodes.
2. Configuration: Configuration of a Replica Group describes which copies are included in the Replica Group and which one is the Primary.
3. Configuration Version: The version number of the Configuration. The version number increments by 1 whenever Configuration changes occur.
4. Configuration Manager: This manages global Configuration components, which ensures the consistency of Configuration data. Configuration change requests are initiated by a Replica node and are then sent to Configuration Manager along with the Version. Configuration Manager verifies that the Version is correct. If not, the change request is rejected.
5. Query & Update: There are two types of Replica Group operations, Query and Update. Query does not change the data, while Update does.
6. Serial Number(sn): This represents the order of each Update operation execution. It increments by 1 for every Update operation, and it is a consecutive number.
7. Prepared List: This is the preparation sequence for Update operations.
8. Committed List: This is the commit sequence for Update operations. The operations in the commit sequence definitely take effect (unless all copies crash). On the same Replica node, Committed List must come before the Prepared List.

##### Pacifica Algorithm - Primary Invariant

With the PacificA algorithm, an error detection mechanism is required to satisfy the following invariant.

When a Replica node deems itself the Primary node at any time, Configuration maintained in Configuration Manager also considers it to be the current Primary. At any time, only one Replica node deems itself the Primary node in this Replica Group.

Primary Invariant can ensure that, when a node deems itself the Primary, it must be the current Primary node. If Primary Invariant cannot be satisfied, Query requests would likely be sent to the Old Primary, which would result in legacy data being read.

How do you ensure Primary Invariant is satisfied? According to the paper, this can be achieved by adopting a Lease mechanism, which is a common method used in distributed systems. Specifically, the Primary node periodically obtains a Lease, and once successfully obtained, it deems itself to be the only Primary node for a set period. It loses Primary status if it has not obtained a new Lease once the period has expired. As long as the CPU in each machine does not have significant clock skew, the effectiveness of the lease mechanism is guaranteed.

As described in the paper, the Lease mechanism has the Primary node send a heartbeat to all Secondary nodes to obtain a Lease, instead of having all nodes obtain a Lease from a centralized component. Using this decentralized model ensures that there is no centralized component that, if it fails, causes all nodes to lose their leases.

##### Pacifica Algorithm - Query

The Query process is relatively simple. Queries can only be sent to the Primary node, and the Primary node returns the corresponding values based on the latest committed data. Since this algorithm requires the Primary Invariant condition to be met, Queries always read the latest committed data.

##### Pacifica Algorithm - Update

The update process is as follows:  

1. Primary node assigns a Serial Number (sn) to an UpdateRequest.
2. The Primary node adds this UpdateRequest to its own Prepared List. Meanwhile, it sends the Prepare request to all Secondary nodes, requiring them to add this UpdateRequest to their Prepared Lists.
3. When all Replica nodes complete Prepare, that is, when the Prepared Lists of all Replica nodes contain the Update request, the Primary node starts to commit the request, adding the UpdateRequest to Committed List and applying the Update. Note that, on the same Replica node, Committed List always comes before the Prepared List, so the Primary node increases the Committed Point when including the Update Request.
4. The result is returned to the Client, and the Update operation is successful.

When the Primary node sends the next request to a Secondary node, the current Committed Point of the Primary is attached to the request, and the Secondary node increases its Committed Point.

### 6 What if we use Zookeeper instead of ES's ZenDiscovery module? 
https://www.alibabacloud.com/blog/elasticsearch-distributed-consistency-principles-analysis-1---node_594358
#### 6.1. Comparison with ZooKeeper

This section describes several methods of implementing major node-related functions in an ES cluster:  

1. Node discovery
2. Master election
3. Error detection
4. Cluster scaling

**About ZooKeeper**

ZooKeeper is used to manage the nodes, configurations, and states in the distributed system and complete the configurations and state synchronization among individual nodes. Many distributed systems rely on ZooKeeper or similar components.

ZooKeeper manages data in the form of a directory tree; each node is referred to as a znode, and each znode consists of three parts:  

1. This is the state information that describes the znode version, permissions, and other information.
2. The date associated with the znode.
3. The child nodes under the znode.

One of the items in stat is ephemeralOwner; if it has a value, it represents a temporary node. This temporary node is deleted after the session ends, and it can be used to assist the application in master election and error detection.

ZooKeeper provides watch functionality that can be used to listen to corresponding events, such as the increase/decrease of a child node under a znode, the increase/decrease of a znode, and the update of a znode.

**Implementing the ES functionality Above Using ZooKeeper**  

1. Node discovery: Configure the ZooKeeper server address in the configuration file of each node. Once the node starts, it tries to register a temporary znode in a ZooKeeper directory. The master of the current cluster listens to increase/decrease child node events in this directory. Whenever a new node is discovered, it adds the new node to the cluster.
2. Master election: When a master-eligible node starts, it tries to register a temporary znode named master in a fixed location. If the registration succeeds, it becomes master; if the registration fails, it listens to changes to this znode. When the master fails, it is automatically deleted because it is a temporary znode; meanwhile, the other master-eligible nodes try to register again. When you use ZooKeeper, you turn the master election into the master.
3. Error detection: Because the znode of the node and the znode of the master are both temporary znodes, if the node fails, the session disconnects from ZooKeeper and the znode is automatically deleted. The master of the cluster only needs to listen to znode change events. If the master fails, other candidate masters listen to the master znode deletion event and try to become the new master.
4. Cluster scaling: The minimum_master_nodes configuration no longer matters when scaling the cluster, which makes scaling easier.

**Advantages and Disadvantages of using ZooKeeper**

ZooKeeper handles some complex distributed consistency issues, simplifying ES operation substantially and helping guarantee data integrity. This is also the common implementation for most distributed systems. While the ES' Zen Discovery module has undergone many bug fixes, there remain critical bugs, and operation and maintenance is difficult.

So, why doesn't ES use ZooKeeper? Perhaps the official developers believe that adding ZooKeeper dependency means relying on one more component, adding complexity to cluster deployment and forcing users to manage one more service during regular operation and maintenance.

Are there any other algorithms available for self-implementation? Of course, there is raft, for example.

#### 6.2. Comparison with Raft

The raft algorithm is a very popular distributed consensus algorithm. It is easier to implement than paxos, and it has been used in a wide variety of distributed systems. Instead of describing the details of this algorithm here, we focus on the master election algorithm to compare the similarities and differences between raft and the ES' current election algorithm:

**Similarities**  

1. Quorum principle: Only the node that gets more than half of the votes can become master.
2. The selected leader must have the latest submitted data: In raft, the nodes with newer data do not vote for nodes with older data, and because getting elected requires a majority of votes, the leader-elect must have the latest submitted data. In ES, the sort priority is higher for nodes with up-to-date versions to ensure this as well.

**Differences**  

1. Proof of correctness: Raft is an algorithm whose correctness has been proved. The correctness of the ES' algorithm is unproven, and any issues will only be found in practice, at which point bugs can be fixed. This is the major difference.
2. Election Cycle term: Raft introduces the concept of Election Cycle. The term plus one for each election round ensures that, within the same term, each participant can only have one vote. ES does not have a term concept during election and is unable to guarantee that each node can only have one vote every round.
3. Election tendency: In raft, if a node has the latest submitted data, there is an opportunity for it to be elected master. In ES, nodes with the same version are sorted by NodeId, and nodes with a lower NodeId always take priority.
