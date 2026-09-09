def email_verifier(email: str):
    required = "@"
    allowerd = ["_","."]
    not_allowed = [" ","<",">",":",";","{","}","[","]","-","+","*","&","^","%","$","#","!"]
    for element in not_allowed:
        if element in email:
            return "Not Accessible"
            break
    return "Accessible"