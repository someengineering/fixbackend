# WebSocket Events

Events are sent in Json Format. Every event will be written as a single line without any line breaks.
Empty lines are allowed and should be ignored by the listener.

## Envelope

All messages published on the WebSocket event channel have the following envelope.
The Listener should implement logic based on the kind of the event.
A specific kind will always have the same format.

```json
{
  "id": "<some unique identifier of the message>",
  "at": "<timestamp in ISO 8601 format>",
  "publisher": "name of the publisher",
  "kind": "type of the event data",
  "data": { }
}
```

Example:
```json
{
    "id": "B5382C1D-2288-4B0E-8CF7-41370FB18232",
    "at": "2023-10-23T12:21:12Z",
    "publisher": "test-publisher",
    "kind": "collect-error",
    "data": {
      "workflow": "collect_and_cleanup", 
      "task": "75aa05da-6695-11ee-a621-dad780437c54", 
      "message": "[aws] Access denied for profile d2iq"
    }  
}
```

## `cloud_account_created` event

When a new cloud account is discovered by AWS CF template, we publish a `cloud_account_created` event.

Example:
```json
{
    "id": "00000000-0000-0000-0000-000000000000",
    "at": "2023-10-23T12:21:12Z",
    "publisher": "cloud-account-service",
    "kind": "cloud_account_created",
    "data": {
      "cloud_account_id": "00000000-0000-0000-0000-000000000000",
      "workspace_id": "00000000-0000-0000-0000-000000000000",
      "aws_account_id": "123456789012",
    }  
}

```


## `collect-progress` event

When a collect workflow is running, we publish a `collect-progress` event on a regular basis.
This event contains progress information for a specific workflow run.
The progress is modeled as a tree of progress information, where the leaves report the actual progress.
Progress of parent nodes can be computed by aggregating the progress of their children.
A progress event with a specific task id replaces any previous progress event with the same task id.


Structure:
```json
{
  "workflow": "<name of the workflow>",
  "task": "<id of the task>",
  "message": {
    "kind": "tree",
    "name": "<name of the progress update>",
    "parts": [
      {
        "kind": "progress",
        "name": "<name of the action that is performed>",
        "path": [ "path", "in", "tree" ],
        "current": "number that represents the current state",
        "total": "number that represents the total state"
      }
    ]
  }
}
```

Example:
```json
{
  "workflow": "collect_and_cleanup",
  "task": "75aa05da-6695-11ee-a621-dad780437c54",
  "message": {
    "kind": "tree",
    "name": "collect_and_cleanup",
    "parts": [
      {
        "kind": "progress",
        "name": "eu-central-1",
        "path": [ "collect", "aws", "development" ],
        "current": 50,
        "total": 100
      },
      {
        "kind": "progress",
        "name": "us-east-1",
        "path": [ "collect", "aws", "development" ],
        "current": 1,
        "total": 1
      },
      {
        "kind": "progress",
        "name": "production",
        "path": [ "collect", "aws" ],
        "current": 1,
        "total": 1
      }
    ]
  }
}
```

This example can be visualized as follows:

```
collect_and_cleanup(75aa05da-6695-11ee-a621-dad780437c54)
└── collect
    └── aws
        ├── development
        │   ├── eu-central-1 <50%>
        │   └── us-east-1 <done>
        └── production <done>
```

Note: One FIX user might have different accounts.
A separate workflow is started for every account.
Multiple updates for the same tenant might be received.


## `collect-error` event

In case an error happens during the collect phase, we publish a `collect-error` event.
Note: we might want to drop those events until we know exactly how to represent this information.

Structure:
```json
{
  "workflow": "<name of the workflow>",
  "task": "<id of the task>",
  "message": "<error message>"
}
```

A collect always belongs to a workflow. The workflow is the name of the workflow that is currently running.
Every workflow run has a specific task identifier.
The error message itself is a string that can be displayed to the user.

