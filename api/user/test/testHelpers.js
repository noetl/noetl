var co = require('co');

var app = require('../');
module.exports.request = require('supertest').agent(app.listen());

var users = app.users;
module.exports.users = users;
console.log("testHeplers.js users: ", users);

module.exports.removeAll = function (done) {
	co(function* () {
		yield users.remove({});
		done();
	});
};

module.exports.test_user = { name: 'Alexey', city: 'Tbilisi, Georgia' };

//# sourceMappingURL=testHelpers.js.map

//# sourceMappingURL=testHelpers.js.map

//# sourceMappingURL=testHelpers.js.map