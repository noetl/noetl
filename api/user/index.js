/**
 * Created by alexey kuksin on 5/4/16.
 */
var koa = require("koa");
var app = module.exports = koa();
var koaRoutes = require("koa-route");
var parse = require("co-body");
var monk = require("monk");
var wrap = require("co-monk");
var db = monk("localhost/usersApi");
var users = wrap(db.get("users"));

module.exports.users = users;

app.use(koaRoutes.post("/", add));
app.use(koaRoutes.get("/:id", get));
app.use(koaRoutes.put("/:id", update));
app.use(koaRoutes.del("/:id", remove));

function * add() {
    var postedUser = yield parse(this);
    if(!exists(postedUser.name)){
        this.set('ValidationError', 'Name is required');
        this.status = 200;
        return;
    };

    if(!exists(postedUser.city)){
        this.set('ValidationError', 'City is required');
        this.status = 200;
        return;
    };

    var insertedUser = yield users.insert(postedUser);

    this.set("location", this.originalUrl + "/" + insertedUser._id);
    this.status = 201;
};

function *get(id) {
    var user = yield users.findById(id);
    this.body = user;
    this.status = 200;
};

function * update(id) {
    var userFromRequest = yield parse(this);

    yield users.updateById(id, userFromRequest);

    var prefixOfUrl = this.originalUrl.replace(id, "");
    this.set("location", prefixOfUrl + id);
    this.status = 204;
}

function * remove(id) {
    yield users.remove({_id : id});
    this.status = 200;
};

var exists = function (value) {
    if(value === undefined)
        return false;
    if(value === null)
        return false;
    return true;
};

//if(process.env.standalone){
//    app.listen(3000);
//}