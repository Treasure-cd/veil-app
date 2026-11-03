```text
APP OPENS
    |
    v
Check for existing Veil session
    |
    +---- Valid session ----> Restore authenticated state
    |
    +---- No/expired session
                |
                v
          Show app as guest
                |
                v
          Connect wallet
                |
                v
          Request challenge
                |
                v
          Sign challenge message
                |
                v
          Submit signature
                |
                v
          Receive JWT + user
                |
                v
          Persist session
                |
                v
          AUTHENTICATED
```
