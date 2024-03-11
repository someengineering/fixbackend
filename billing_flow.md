
# Billing Flow

Here are a couple of diagrams that illustrate the billing flow. Setting up means getting a new AWS Marketplace subscription or doing the same flow with an existing subscription. 


## Setting up a subscription with a single workspace

Here is the base case where a user has a single workspace. The assignment of the subscription to the workspace is done automatically. Workspace selection dialog is not shown.

![diagram](images/subscription_setup_single_workspace.png)

<details>

<summary>source</summary>

```plantuml
@startuml subscription_setup_single_workspace

actor User as U
participant "FixBackend API" as FB
participant "AWS Marketplace" as AMP
participant AwsMarketplaceHandler as AH
participant AWS as AWS
collections SubscriptionRepo as S
collections WorkspaceRepo as WS

U -> FB: Clicks on the AWS Marketplace button
FB -> U: Redirect link to AWS Marketplace
U -> AMP: Clicks "Set up your account"
AMP -> U: Redirect Fix Backend callback endpoint
U -> FB: Sends the callback to FixBackend
FB -> FB: Self-redirect to use the SameSite cookie
FB -> AH: Create a new subscription
AH -> AWS: Resolve customer information
AWS -> AH: Returns the customer information
AH -> S: Create a new subscription
AH -> WS: Add subscription to workspace
AH -> FB: (subscription, workspace_assigned=true)
FB -> U: Redirect to "/" with a success message
@enduml
```

</details>

## Setting up subscription with multiple workspaces

A bit more complex case where a user has multiple workspaces. The subscription is not assigned to any workspace by default. Instead, the user is prompted to select a workspace to assign the subscription to.


![diagram](images/subscription_setup_multiple_workspaces.png)

<details>

<summary>source</summary>

```plantuml
@startuml subscription_setup_multiple_workspaces

actor User as U
participant "FixBackend API" as FB
participant "AWS Marketplace" as AMP
participant AwsMarketplaceHandler as AH
participant AWS as AWS
collections SubscriptionRepo as S
collections WorkspaceRepo as WS

U -> FB: Clicks on the AWS Marketplace button
FB -> U: Redirect link to AWS Marketplace
U -> AMP: Clicks "Set up your account"
AMP -> U: Redirect Fix Backend callback endpoint
U -> FB: Sends the callback to FixBackend
FB -> FB: Self-redirect to use the SameSite cookie
FB -> AH: Create a new subscription
AH -> AWS: Resolve customer information
AWS -> AH: Returns the customer information
AH -> S: Create a new subscription
note over AH: Subscription is not assigned to any workspace \nbecause the user has multiple workspaces
AH -> FB: (subscription, workspace_assigned=false)
FB -> U: Redirect to /subscription/choose-workspace
loop until receives 200 OK
    U -> FB: add subscription to workspace
end
FB -> FB: validate permissions to update billing
FB -> S: validate that the subscription was created by the current user
FB -> WS: Add subscription to workspace
FB -> U: 200 OK
@enduml
```

</details>

## Updating the product tier


![diagram](images/product_tier_update.png)

<details>

<summary>source</summary>

```plantuml
@startuml product_tier_update

actor User as U
participant "FixBackend API" as FB
participant "BillingEntryService" as B
collections WorkspaceRepo as WS
queue DomainEvents as Q

U -> FB: selects the produuct tier
FB -> FB: validates user permissions
FB -> B: update the product tier
B -> B: checks the subscription if paid product tier
B -> WS: update the product tier
B -> Q: publish ProductTierChanged
B -> FB: updated workspace
FB -> B: get product tier
B -> FB: returns the product tier
FB -> U: 200 OK

@enduml
```

</details>